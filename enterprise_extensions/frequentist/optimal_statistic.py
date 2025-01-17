from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

import numpy as np
import scipy.linalg as sl

from enterprise_extensions import models

from enterprise.signals import utils
from enterprise.signals import signal_base

import warnings


## Define the output to be on a single line.
def warning_on_one_line(message, category, filename, lineno, file=None, line=None):
    return '%s:%s: %s: %s\n' % (filename, lineno, category.__name__, message)

## Override default format.
warnings.formatwarning = warning_on_one_line

class OptimalStatistic(object):
    """
    Class for the Optimal Statistic as used in the analysis paper.

    This class can be used for both standard ML or noise-marginalized OS.

    :param psrs: List of `enterprise` Pulsar instances.
    :param bayesephem: Include BayesEphem model. Default=True
    :param gamma_common:
        Fixed common red process spectral index value. By default we
        vary the spectral index over the range [0, 7].
    :param orf:
        String representing which overlap reduction function to use.
        By default we do not use any spatial correlations. Permitted
        values are ['hd', 'dipole', 'monopole'].

    """

    def __init__(self, psrs, bayesephem=True, gamma_common=4.33, orf='hd',
                 wideband=False, select=None, noisedict=None, pta=None):

        # initialize standard model with fixed white noise and
        # and powerlaw red and gw signal

        if pta is None:
            self.pta = models.model_2a(psrs, psd='powerlaw',
                                       bayesephem=bayesephem,
                                       gamma_common=gamma_common,
                                       wideband=wideband,
                                       select='backend', noisedict=noisedict)
        else:
            self.pta = pta


        self.gamma_common = gamma_common
        # get frequencies here
        self.freqs = self._get_freqs(psrs)

        # get F-matrices and set up cache
        self.Fmats = self.get_Fmats()
        self._set_cache_parameters()

        # pulsar locations
        self.psrlocs = [p.pos for p in psrs]

        # overlap reduction function
        if orf == 'hd':
            self.orf = utils.hd_orf
        elif orf == 'dipole':
            self.orf = utils.dipole_orf
        elif orf == 'monopole':
            self.orf = utils.monopole_orf
        else:
            raise ValueError('Unknown ORF!')

    def compute_os(self, params=None):
        """
        Computes the optimal statistic values given an
        `enterprise` parameter dictionary.

        :param params: `enterprise` parameter dictionary.

        :returns:
            xi: angular separation [rad] for each pulsar pair
            rho: correlation coefficient for each pulsar pair
            sig: 1-sigma uncertainty on correlation coefficient for each pulsar pair.
            OS: Optimal statistic value (units of A_gw^2)
            OS_sig: 1-sigma uncertainty on OS

        .. note:: SNR is computed as OS / OS_sig.

        """

        if params is None:
            params = {name: par.sample() for name, par
                      in zip(self.pta.param_names, self.pta.params)}
        else:
            # check to see that the params dictionary includes values
            # for all of the parameters in the model
            for p in self.pta.param_names:
                if p not in params.keys():
                    msg = '{0} is not included '.format(p)
                    msg += 'in the parameter dictionary. '
                    msg += 'Drawing a random value.'

                    warnings.warn(msg);

        # get matrix products
        TNrs = self.get_TNr(params=params)
        TNTs = self.get_TNT(params=params)
        FNrs = self.get_FNr(params=params)
        FNFs = self.get_FNF(params=params)
        FNTs = self.get_FNT(params=params)

        phiinvs = self.pta.get_phiinv(params, logdet=False)

        X, Z = [], []
        for TNr, TNT, FNr, FNF, FNT, phiinv in zip(TNrs, TNTs, FNrs, FNFs, FNTs, phiinvs):

            Sigma = TNT + (np.diag(phiinv) if phiinv.ndim == 1 else phiinv)
            try:
                cf = sl.cho_factor(Sigma)
                SigmaTNr = sl.cho_solve(cf, TNr)
                SigmaTNF = sl.cho_solve(cf, FNT.T)
            except np.linalg.LinAlgError:
                SigmaTNr = np.linalg.solve(Sigma, TNr)
                SigmaTNF = np.linalg.solve(Sigma, FNT.T)

            FNTSigmaTNr = np.dot(FNT, SigmaTNr)
            X.append(FNr - FNTSigmaTNr)
            Z.append(FNF - np.dot(FNT, SigmaTNF))

        npsr = len(self.pta._signalcollections)
        rho, sig, ORF, xi = [], [], [], []
        for ii in range(npsr):
            for jj in range(ii+1, npsr):
                if self.gamma_common is None and 'gw_gamma' in params.keys():
                    print('{0:1.2}'.format(params['gw_gamma']))
                    phiIJ = utils.powerlaw(self.freqs, log10_A=0,
                                           gamma=params['gw_gamma'])
                else:
                    phiIJ = utils.powerlaw(self.freqs, log10_A=0,
                                           gamma=self.gamma_common)

                top = np.dot(X[ii], phiIJ * X[jj])
                bot = np.trace(np.dot(Z[ii]*phiIJ[None,:], Z[jj]*phiIJ[None,:]))

                # cross correlation and uncertainty
                rho.append(top / bot)
                sig.append(1 / np.sqrt(bot))

                # Overlap reduction function for PSRs ii, jj
                ORF.append(self.orf(self.psrlocs[ii], self.psrlocs[jj]))

                # angular separation
                xi.append(np.arccos(np.dot(self.psrlocs[ii], self.psrlocs[jj])))

        rho = np.array(rho)
        sig = np.array(sig)
        ORF = np.array(ORF)
        xi = np.array(xi)
        OS = (np.sum(rho*ORF / sig ** 2) / np.sum(ORF ** 2 / sig ** 2))
        OS_sig = 1 / np.sqrt(np.sum(ORF ** 2 / sig ** 2))

        return xi, rho, sig, OS, OS_sig

    def compute_noise_marginalized_os(self, chain, param_names=None, N=10000):
        """
        Compute noise marginalized OS.

        :param chain: MCMC chain from Bayesian run.
        :param param_names: list of parameter names for the chain file
        :param N: number of iterations to run.

        :returns: (os, snr) array of OS and SNR values for each iteration.

        """

        # check that the chain file has the same number of parameters as the model
        if chain.shape[1] - 4 != len(self.pta.param_names):
            msg = 'MCMC chain does not have the same number of parameters '
            msg += 'as the model.'

            warnings.warn(msg)

        opt, sig = np.zeros(N), np.zeros(N)
        setpars = {}
        for ii in range(N):
            idx = np.random.randint(0, chain.shape[0])

            # if param_names is not specified, the parameter dictionary
            # is made by mapping the values from the chain to the
            # parameters in the pta object
            if param_names is None:
                setpars.update(self.pta.map_params(chain[idx, :-4]))
            else:
                setpars = dict(zip(param_names,chain[idx,:-4]))
            _, _, _, opt[ii], sig[ii] = self.compute_os(params=setpars)

        return (opt, opt/sig)

    def compute_noise_maximized_os(self, chain, param_names=None):
        """
        Compute noise maximized OS.

        :param chain: MCMC chain from Bayesian run.

        :returns:
            xi: angular separation [rad] for each pulsar pair
            rho: correlation coefficient for each pulsar pair
            sig: 1-sigma uncertainty on correlation coefficient for each pulsar pair.
            OS: Optimal statistic value (units of A_gw^2)
            SNR: OS / OS_sig

        """

        # check that the chain file has the same number of parameters as the model
        if chain.shape[1] - 4 != len(self.pta.param_names):
            msg = 'MCMC chain does not have the same number of parameters '
            msg += 'as the model.'

            warnings.warn(msg)

        idx = np.argmax(chain[:, -4])

        # if param_names is not specified, the parameter dictionary
        # is made by mapping the values from the chain to the
        # parameters in the pta object
        if param_names is None:
            setpars = (self.pta.map_params(chain[idx, :-4]))
        else:
            setpars = dict(zip(param_names,chain[idx,:-4]))

        xi, rho, sig, Opt, Sig = self.compute_os(params=setpars)

        return (xi, rho, sig, Opt, Opt/Sig)

    def get_Fmats(self, params={}):
        """Kind of a hack to get F-matrices"""
        Fmats = []
        for sc in self.pta._signalcollections:
            ind = []
            for signal, idx in sc._idx.items():
                if signal.signal_name == 'red noise' and signal.signal_id in ['gw','gw_crn']:
                    ind.append(idx)
            ix = np.unique(np.concatenate(ind))
            Fmats.append(sc.get_basis(params=params)[:, ix])

        return Fmats

    def _get_freqs(self,psrs):
        """ Hackish way to get frequency vector."""
        for sig in self.pta._signalcollections[0]._signals:
            if sig.signal_name == 'red noise' and sig.signal_id in ['gw','gw_crn']:
                sig._construct_basis()
                freqs = np.array(sig._labels[''])
                break
        return freqs

    def _set_cache_parameters(self):
        """ Set cache parameters for efficiency. """
        self.white_params = []
        self.basis_params = []
        self.delay_params = []

        for sc in self.pta._signalcollections:
            self.white_params.extend(sc.white_params)
            self.basis_params.extend(sc.basis_params)
            self.delay_params.extend(sc.delay_params)

    def get_TNr(self, params={}):
        return self.pta.get_TNr(params=params)

    @signal_base.cache_call(['white_params', 'delay_params'])
    def get_FNr(self, params={}):
        FNrs = []
        for ct, sc in enumerate(self.pta._signalcollections):
            N = sc.get_ndiag(params=params)
            F = self.Fmats[ct]
            res = sc.get_detres(params=params)
            FNrs.append(N.solve(res, left_array=F))
        return FNrs

    @signal_base.cache_call(['white_params'])
    def get_FNF(self, params={}):
        FNFs = []
        for ct, sc in enumerate(self.pta._signalcollections):
            N = sc.get_ndiag(params=params)
            F = self.Fmats[ct]
            FNFs.append(N.solve(F, left_array=F))
        return FNFs

    def get_TNT(self, params={}):
        return self.pta.get_TNT(params=params)

    @signal_base.cache_call(['white_params', 'basis_params'])
    def get_FNT(self, params={}):
        FNTs = []
        for ct, sc in enumerate(self.pta._signalcollections):
            N = sc.get_ndiag(params=params)
            F = self.Fmats[ct]
            T = sc.get_basis(params=params)
            FNTs.append(N.solve(T, left_array=F))
        return FNTs
