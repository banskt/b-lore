import numpy as np
import os
import ctypes
from inference import quasi_laplace

def create(nsnps, cmax, target, pi, mu, sig2, vmin, mureg, sigreg2, precll, is_covariate):
    ''' At every step of iteration, zstates are created to account for the causal SNPs. 
        It is a sparse matrix (of 0s and 1s) represented here as a list of lists. 
        Each list element, representing a row of the matrix, is another list of non-zero column positions.
        A matrix M = [[1 0 0 0]
                      [0 0 1 0]
                      [0 1 0 1]]
        would be represented as [[0], [2], [1,3]]
        We use a branch and bound algorithm (see text / note example below) to generate zstates.
        For covariates, all z's are 1 z = [1 1 1 ... 1]
        
        Input: nsnps    number of snps in the locus
               cmax     maximum number of causal SNPs allowed
               params   current set of hyperparameters
               target   proportion of maximum likelihood to account for
               
        Example: Consider a set of 4 SNPs
                 Initial zstates with ||z|| = 1 are 
                     [[0], [1], [2], [3]]
                 Assuming states [1] and [3] can account for 98% of the maximum likelihood,
                 our new ztstates for ||z|| = 2 would be
                     [[0,1], [1,2], [1,3], [0,3], [2,3]]
                 Again, if [0,1] and [1,3] can account for 98% of the maximum likelihood,
                 then for ||z|| = 3, our new zstates are 
                     [[0,1,2], [0,1,3], [1,2,3]]
                 and so on ...
    '''

    if not is_covariate: # Compute the zstates only for SNP loci

        # The looping would be done in C++ for speed up
        _path = os.path.dirname(__file__)
        lib = np.ctypeslib.load_library('../lib/zstates.so', _path)
        zcreate = lib.create_zstates
        zcreate.restype  = ctypes.c_int
        zcreate.argtypes = [ctypes.c_int,
                            ctypes.c_int,
                            ctypes.c_int,
                            np.ctypeslib.ndpointer(ctypes.c_int, flags='C_CONTIGUOUS, ALIGNED'),
                            np.ctypeslib.ndpointer(ctypes.c_int, flags='C_CONTIGUOUS, ALIGNED')]
    
    
        # Initialize for ||z|| = 0 and 1
        zstates = [[]] 
        newk = [[i] for i in range(nsnps)]
        zstates += newk
    
        if cmax > 1:
            oldk = newk
            posterior = quasi_laplace.margloglik_zcomps(pi, mu, sig2, zstates, vmin, mureg, sigreg2, precll)
            prob = np.array(posterior[-len(newk):])
            probsum = np.sum(prob)
            old_probsum = posterior[0]
            #print ("Total probsum:", probsum)
    
        # Iterate over ||z|| = 2 to cmax
        norm = 1
        while norm < cmax:

            if probsum < (1 - target) * old_probsum:
                break

            norm += 1
            sort = np.argsort(prob)[::-1]         # index of decreasing order of prob. prob[sort] should be the sorted array
            cum  = np.cumsum(prob[sort])          # cumulative sum -- should be greater than target value
            targ = probsum * target               # target value
            nsel = np.where(cum > targ)[0]        # find when cum > targ
    
            # assure there is at least one zstate 
            # sometimes posterior values could be so low that they can round off to zero
            # and there would be no state with cum > targ
            if len(nsel) == 0:
                break;
            else:
                nsel = nsel[0] + 1                # when cum > targ for first time (add +1 since indexing starts from 0 / if nsel[0] = 4, then there are 5 states with higher probabilities)
                sel  = sort[:nsel]                # These are our new selection
                sel  = np.sort(sel)               # How about sorting them?
                nsel = len(sel)
    
            # For debug
            #print(probsum)
            #print(prob[sort][:10] / probsum)
    
            # These are our leading states from which terms with norm (k+1) will be created
            leadk = [oldk[sel[i]] for i in range(nsel)]
    
            # for first lead create all possible combinations
            # from next lead onwards do not include duplicate combinations.
            #    Note that a duplicate (k+1) entry is possible iff 
            #    two k-mers have at least (k-1) similar elements.
            #    e.g. [2,4,5,8] can be obtained from [2,4,5], [2,4,8], [2,5,8] or [4,5,8]
            # check previous leads to see if any of them has (k-1) elements similar to the current one
            # If so discard the duplicate.
            #
            # ^^^ the above logic has now been moved to a C++ function for speed up. 
            # get the new zstates from a C++ function
            leadk      = np.array(leadk, dtype=np.int32).reshape(nsel * (norm-1))
            maxnewsize = nsel * (nsnps - norm + 1) * norm
            newz       = np.zeros(maxnewsize, dtype=np.int32)
            newstates  = zcreate(nsel, norm-1, nsnps, leadk, newz)
            newsize    = newstates * norm
            result     = np.array(newz[:newsize]).reshape((newstates, norm))
            newk       = [sorted(list(result[i])) for i in range(newstates)]
    
    
            zstates += newk
    
            # Stop iteration if sum(new posterior) is < 0.02 times sum(old posterior)
            posterior = quasi_laplace.margloglik_zcomps(pi, mu, sig2, zstates, vmin, mureg, sigreg2, precll)
            prob        = np.array(posterior[-len(newk):])
            old_probsum = probsum
            probsum     = np.sum(prob)
            oldk = newk

    else: # define zstates for covariate locus

        zstates = [[i for i in range(nsnps)]]

    return zstates