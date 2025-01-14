import os, sys, shutil
sys.path.append('/projects/b1139/environments/emod_torch_tobias/lib/python3.8/site-packages/')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

from botorch.utils.transforms import unnormalize

from gpytorch.constraints import Interval, GreaterThan, LessThan

sys.path.append("../")
from batch_generators.expected_improvement import ExpectedImprovement
from batch_generators.turbo_thompson_sampling import TurboThompsonSampling
from batch_generators.batch_generator_array import BatchGeneratorArray

from emulators.GP import ExactGP, ExactMultiTaskGP
from bo import BO
from plot import *

from my_func import my_func as myFunc
from compare_to_data.run_full_comparison import plot_all_comparisons
from compare_to_data.run_full_comparison import compute_LL_across_all_sites_and_metrics
from clean_all import clean_analyzers
from translate_parameters import translate_parameters

import manifest as manifest
import torch
from torch import tensor

torch.set_default_dtype(torch.float64)

exp_label = "hyperparam_240804"

output_dir = f"output/{exp_label}"
best_dir = f"output/{exp_label}" 


# BO specifications
init_samples = 1000
init_batches = 10

emulator_batch_size = 100
failure_limit=5
gp_max_eval = 5000

# Define the Problem, it must be a functor
class Problem:
    def __init__(self,workdir="checkpoints/emod"):
        self.dim = 20 # mandatory dimension
        self.ymax = None #max value
        self.best = None
        self.n = 0
        self.workdir = workdir
        try:
            self.ymax = np.loadtxt(f"{self.workdir}/emod.ymax.txt").astype(float)
            self.n = np.loadtxt(f"{self.workdir}/emod.n.txt").astype(int)
        except IOError:
            self.ymax = None
            self.n = 0

        os.makedirs(os.path.relpath(f'{self.workdir}'), exist_ok=True)

    # The input is a vector that contains multiple set of parameters to be evaluated
    def __call__(self, X):
        # Each set of parameter x is evaluated
        # Note that parameters are samples from the unit cube in Botorch
        # Here we map unnormalizing them before calling the square function
        # Finally, because we want to minimize the function, we negate the return value
        # Y = [-myFunc(x) for x in unnormalize(X, [-5, 5])]
        # We return both X and Y, this allows us to disard points if so we choose
        # To remove a set of parameters, we would remove it from both X and Y

        # Finally, we need to return each y as a one-dimensional tensor (since we have just one dimension)
        # 
        # rewrite myfunc as class so we can keep track of things like the max value - aurelien does plotting each time but only saves when the new max > old max - would also allow for easier saving of outputs if desired. would also potentially help with adding iterations to param_set number so we don't reset each time. not sure yet if better to leave existing myfunc or pull everything into this
        param_key=pd.read_csv("test_parameter_key.csv")
        wdir=os.path.join(f"{self.workdir}/LF_{self.n}")
        os.makedirs(wdir,exist_ok=True) 
        Y0 = myFunc(X,wdir,JS=False) 
        # if self.n==0:
        #      #Y0=compute_LL_across_all_sites_and_metrics(numOf_param_sets=100)
        #      Y0=pd.read_csv(f"{self.workdir}/all_LL.csv")
        #      X=pd.read_csv(f"{self.workdir}/LF_{self.n}/translated_params.csv")
        #      ps = max(X['param_set'])
        #      X=X['unit_value']
        #      X = ["torch."+x for x in X]
        #      X = [eval(x) for x in X]
        #      X=[x.numpy().tolist() for x in X]
        # 
        #      X = np.array_split(X, ps)
        # 
        # else:
        #     Y0=myFunc(X,wdir,JS=False)
        
        Y1 = Y0
        
        if self.n == 0:
            Y0['round'] = [self.n] * len(Y0)
            Y0.to_csv(f"{self.workdir}/all_LL.csv")
        else:
            Y0['round'] = [self.n] * len(Y0)
            score_df=pd.read_csv(f"{self.workdir}/all_LL.csv")
            score_df=pd.concat([score_df,Y0])
            score_df.to_csv(f"{self.workdir}/all_LL.csv")
        
        Y1['ll'] = (Y1['ll']  / (Y1['baseline'])) * (Y1['my_weight']) 
        
        Y = Y1.groupby("param_set").agg({"ll": lambda x: x.sum(skipna=False)}).reset_index().sort_values(by=['ll'])
        Ym = Y1.groupby("param_set").agg({"ll": lambda x: x.min(skipna=False)}).reset_index().sort_values(by=['ll'])
        params=Y['param_set']
        Y = Y['ll']
        Ym=Ym['ll']
        if self.n==0:
            # Mask score for team default X_prior
            Y[0]= float("nan")
            Ym[0]= float("nan")
            
        xc = []
        yc = []
        ym = []
        ysc = []
        pc = []
        
        for j in range(len(Y)):
            if pd.isna(Y[j]):
                continue
            else:
                xc.append(X[j].tolist())
                yc.append([Y[j]])
                ym.append([Ym[j]])
                sub=Y1[Y1['param_set']==params[j]]
                ysc.append(sub['ll'].to_list())
                pc.append(params[j])
        
        xc2=[tuple(i) for i in xc]
        links=dict(zip(xc2,yc)) 
        pset=dict(zip(pc,yc))
        links_m=dict(zip(xc2,ym))
        pset_m=dict(zip(pc,ym))
        
        X_out = torch.tensor(xc,dtype=torch.float64)
        print("X_out")
        print(X_out)
        
        Y_out = torch.tensor(yc)
        Y_m_out = torch.tensor(ym)
        #Y_out = torch.stack([torch.tensor(y) for y in ysc],-1)
        print("Y_out")
        print(Y_out)
        print(Y_out.shape)
        print("Y_m_out")
        print(Y_m_out)
        print(Y_m_out.shape)

        # If new best value is found, save it and some other data
        if self.ymax is None or self.n == 0:
            self.ymax = max(links_m.values())
            
            best_p = max(pset_m,key=pset_m.get)
            best_x = max(links_m,key=links_m.get)
            self.best = translate_parameters(param_key,best_x,ps_id=best_p)
            
            np.savetxt(f"{self.workdir}/emod.ymax.txt", [self.ymax])
            np.savetxt(f"{self.workdir}/LF_{self.n}/emod.ymax.txt", [self.ymax])
            self.best.to_csv(f"{self.workdir}/LF_{self.n}/emod.best.csv")
            plot_all_comparisons(param_sets_to_plot=[1],plt_dir=self.workdir)
            plot_all_comparisons(param_sets_to_plot=[max(pset_m,key=pset_m.get),1],plt_dir=os.path.join(f"{self.workdir}/LF_{self.n}"))
            shutil.copytree(f"{manifest.simulation_output_filepath}",f"{self.workdir}/LF_{self.n}/SO",dirs_exist_ok = True)            
            self.n += 1
            np.savetxt(f"{self.workdir}/emod.n.txt", [self.n])
            
        else: 
            if max(links_m.values())[0] > self.ymax:
                self.ymax = max(links_m.values()) #weighted_lf  
                best_p = max(pset_m,key=pset_m.get)
                best_x = max(links_m,key=links_m.get)
                self.best = translate_parameters(param_key,best_x,best_p)
                self.best.to_csv(f"{self.workdir}/LF_{self.n}/emod.best.csv")

            plot_all_comparisons(param_sets_to_plot=[max(pset_m,key=pset_m.get)],plt_dir=os.path.join(f"{self.workdir}/LF_{self.n}"))
              
            np.savetxt(f"{self.workdir}/emod.ymax.txt", [self.ymax])
            np.savetxt(f"{self.workdir}/LF_{self.n}/emod.ymax.txt", [self.ymax])
            shutil.copytree(f"{manifest.simulation_output_filepath}",f"{self.workdir}/LF_{self.n}/SO",dirs_exist_ok = True)
            self.n += 1
            np.savetxt(f"{self.workdir}/emod.n.txt", [self.n])
        
        return X_out, Y_m_out


problem = Problem(workdir=f"output/{exp_label}")

# Delete everything and restart from scratch 
# Comment this line to restart from the last state instead
#if os.path.exists(output_dir): shutil.rmtree(output_dir)
#if os.path.exists(best_dir): shutil.rmtree(best_dir)

# at beginning of workflow, cleanup all sbatch scripts for analysis
clean_analyzers()

# Create the GP model
# See emulators/GP.py for a list of GP models
# Or add your own, see: https://botorch.org/docs/models

#model = ExactGP(noise_constraint=GreaterThan(1e-6))
model = ExactGP(noise_constraint=GreaterThan(1e-6))

# Create batch generator(s)
#batch_size 64 when running in production
tts = TurboThompsonSampling(batch_size=emulator_batch_size, failure_tolerance=failure_limit, dim=problem.dim) #64
batch_generator = tts #BatchGeneratorArray([tts, ei])

# Create the workflow
bo = BO(problem=problem, model=model, batch_generator=batch_generator, checkpointdir=output_dir, max_evaluations=gp_max_eval)

# Sample and evaluate sets of parameters randomly drawn from the unit cube
#bo.initRandom(2)

# Usual random init sample, with team default Xprior
team_default_params = [0.235457679394,  # Antigen switch rate (7.65E-10) 
                       0.166666666667,  # Gametocyte sex ratio (0.2) 
                       0.100343331888,  # Base gametocyte mosquito survival rate (0.002)
                       0.394437557888,  # Base gametocyte production rate (0.0615)
                       0.50171665944,   # Falciparum MSP variants (32)
                       0.0750750750751, # Falciparum nonspecific types (76)
                       0.704339142192,  # Falciparum PfEMP1 variants (1070)
                       0.28653200892,   # Fever IRBC kill rate (1.4)
                       0.584444444444,  # Gametocyte stage survival rate (0.5886)
                       0.506803355556,  # MSP Merozoite Kill Fraction (0.511735)
                       0.339794000867,  # Nonspecific antibody growth rate factor (0.5)  
                       0.415099999415,  # Nonspecific Antigenicity Factor (0.4151) 
                       0.492373751573,  # Pyrogenic threshold (15000)
                       0]               # Max Individual Infections (3)
                       
team_default_params2 = [0.235457679394, # Antigen switch rate (7.65E-10) 
                       0.166666666667,  # Gametocyte sex ratio (0.2) 
                       0.236120668037,  # Base gametocyte mosquito survival rate (0.00088) **
                       0.394437557888,  # Base gametocyte production rate (0.0615)
                       0.50171665944,   # Falciparum MSP variants (32)
                       0.0750750750751, # Falciparum nonspecific types (76)
                       0.704339142192,  # Falciparum PfEMP1 variants (1070)
                       0.28653200892,   # Fever IRBC kill rate (1.4)
                       0.584444444444,  # Gametocyte stage survival rate (0.5886)
                       0.506803355556,  # MSP Merozoite Kill Fraction (0.511735)
                       0.339794000867,  # Nonspecific antibody growth rate factor (0.5)  
                       0.415099999415,  # Nonspecific Antigenicity Factor (0.4151) 
                       0.492373751573,  # Pyrogenic threshold (15000)
                       0,               # Max Individual Infections (3)
                       0.666666666666,  # Erythropoesis Anemia Effect Size (3.5)
                       0.755555555555,  # RBC Destruction Multiplier (3.9)
                       0.433677,        # Cytokine Gametocyte Killing (0.02)
                       0,               # InnateImmuneDistributionFlag (CONSTANT)
                       0,               # InnateImmuneDistribution1 (na)
                       0]               # InnateImmuneDistribution2 (na)


bo.initRandom(init_samples,
              n_batches = init_batches,
              Xpriors = [team_default_params2])

# Run the optimization loop
bo.run()


# x=pd.read_csv("test_parameter_key.csv")
# parameter_labels=x['parameter_label'].to_list()
# print("Here")
# # Plot
plot_runtimes(bo)
plt.savefig(f'{output_dir}/runtime', bbox_inches="tight")
plot_MSE(bo,n_init=1)
plt.savefig(f'{output_dir}/mse', bbox_inches="tight")
# plot_convergence(bo, negate=True)
# plt.savefig(f'{output_dir}/convergence', bbox_inches="tight")
plot_prediction_error(bo)
plt.savefig(f'{output_dir}/pred_error', bbox_inches="tight")
# plot_X_flat(bo, param_key = x, labels=parameter_labels)
# plt.savefig(f'{output_dir}/x_flat', bbox_inches="tight")
# #plot_space(bo, -5**2, 0, labels="X")
# #plt.savefig(f'{output_dir}/space', bbox_inches="tight")
# plot_y_vs_posterior_mean(bo,n_init=1)
# plt.savefig(f'{output_dir}/posterior_mean', bbox_inches="tight")
