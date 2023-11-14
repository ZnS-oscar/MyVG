import sys
import json
import torch
import tqdm
import time
import warnings
import os.path as osp
import torch.nn as nn
from torch import optim
from termcolor import colored
import numpy as np

import pickle
from referit3d.in_out.pt_datasets.utils import instance_labels_of_context
from referit3d.in_out.arguments import parse_arguments
from referit3d.in_out.neural_net_oriented import load_scan_related_data, load_referential_data
from referit3d.in_out.neural_net_oriented import compute_auxiliary_data, trim_scans_per_referit3d_data
from referit3d.in_out.pt_datasets.listening_dataset import make_data_loaders
from referit3d.utils import set_gpu_to_zero_position, create_logger, seed_training_code
from referit3d.utils.tf_visualizer import Visualizer
from referit3d.models.referit3d_net import ReferIt3DNet_transformer
from referit3d.models.referit3d_net_utils import single_epoch_train, evaluate_on_dataset
from referit3d.models.utils import load_state_dicts, save_state_dicts
from referit3d.analysis.deepnet_predictions import analyze_predictions
from transformers import BertTokenizer, BertModel
from referit3d.in_out.arguments import parse_arguments
from referit3d.in_out.neural_net_oriented import load_scan_related_data
def sample_scan_object(object, n_points):
    sample = object.sample(n_samples=n_points)
    return np.concatenate([sample['xyz'], sample['color']], axis=1)

if __name__ == '__main__':

    # load from txt
    class_to_idx_path = "class_to_idx.txt"
    with open("class_to_idx.txt", 'r') as class_to_idx_file:
        class_to_idx = json.load(class_to_idx_file)
        
    # Parse arguments
    args = parse_arguments()
    # Prepare GPU environment
    set_gpu_to_zero_position(args.gpu)  # Pnet++ seems to work only at "gpu:0"

    device = torch.device('cuda')
    seed_training_code(args.random_seed)
    # Prepare the Listener
    n_classes = len(class_to_idx) - 1  # -1 to ignore the <pad> class    
    pad_idx = class_to_idx['pad']

    # Object-type classification
    class_name_list = []
    for cate in class_to_idx:
        class_name_list.append(cate)

    # tokenizer = BertTokenizer.from_pretrained(args.bert_pretrain_path)
    # class_name_tokens = tokenizer(class_name_list, return_tensors='pt', padding=True)
    # for name in class_name_tokens.data:
    #     class_name_tokens.data[name] = class_name_tokens.data[name].cuda()

    gpu_num = len(args.gpu.strip(',').split(','))
    model = ReferIt3DNet_transformer(args, n_classes, class_name_tokens=None, ignore_index=pad_idx)    
    
    model = model.to(device)
    print(model)
    #load model param
    param_list=[
        {'params':model.language_encoder.parameters(),'lr':args.init_lr*0.1},
        {'params':model.refer_encoder.parameters(), 'lr':args.init_lr*0.1},
        {'params':model.object_encoder.parameters(), 'lr':args.init_lr},
        {'params':model.obj_feature_mapping.parameters(), 'lr': args.init_lr},
        {'params':model.box_feature_mapping.parameters(), 'lr': args.init_lr},
        {'params':model.language_clf.parameters(), 'lr': args.init_lr},
        {'params':model.object_language_clf.parameters(), 'lr': args.init_lr},
    ]
    if not args.label_lang_sup:
        param_list.append( {'params':model.obj_clf.parameters(), 'lr': args.init_lr})
    optimizer = optim.Adam(param_list,lr=args.init_lr)
    lr_scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer,[40, 50, 60, 70, 80, 90], gamma=0.65)
    if args.resume_path:
        warnings.warn('Resuming assumes that the BEST per-val model is loaded!')
        # perhaps best_test_acc, best_test_epoch, best_test_epoch =  unpickle...
        loaded_epoch = load_state_dicts(args.resume_path, map_location=device, model=model)
        print('Loaded a model stopped at epoch: {}.'.format(loaded_epoch))
        if not args.fine_tune:
            print('Loaded a model that we do NOT plan to fine-tune.')
            load_state_dicts(args.resume_path, optimizer=optimizer, lr_scheduler=lr_scheduler)
            start_training_epoch = loaded_epoch + 1
            start_training_epoch = 0
            best_test_epoch = loaded_epoch
            best_test_acc = 0
            print('Loaded model had {} test-accuracy in the corresponding dataset used when trained.'.format(
                best_test_acc))
        else:
            print('Parameters that do not allow gradients to be back-propped:')
            ft_everything = True
            for name, param in model.named_parameters():
                if not param.requires_grad:
                    print(name)
                    exist = False
            if ft_everything:
                print('None, all wil be fine-tuned')
            # if you fine-tune the previous epochs/accuracy are irrelevant.
            dummy = args.max_train_epochs + 1 - start_training_epoch
            print('Ready to *fine-tune* the model for a max of {} epochs'.format(dummy))


    # load from txt
    pc_path = "obj_pc.pkl"
    with open(pc_path, 'rb') as pc_file:
        pc = pickle.load(pc_file)
    gtfeat_path = "objects_features.pkl"
    with open(gtfeat_path, 'rb') as gtfeat_file:
        gtfeat = pickle.load(gtfeat_file)

    net=model.object_encoder
    cls_id2feat_avg,cls_id2feat_max,cls_id2feat45d_avg,cls_id2feat45d_max,cls_id2feat45d0_avg,cls_id2feat45d0_max={},{},{},{},{},{}
    cls_id2feat_avgmax={}

    


    # pcs_tensor=torch.tensor(cls_id2pcs[cls_id]).to(device)
    pc_1=pc.unsqueeze(0)
    with torch.no_grad():
        net.eval()
        feat_45d=net(pc_1.repeat(45,1,1))
        feat_bd=net(pc_1)
    # print("pcs_tensor loaded",torch.cuda.memory_allocated())
    aaa=[
    torch.cosine_similarity(feat_45d[0],feat_45d[1],dim=0),
    torch.cosine_similarity(feat_45d[1],feat_45d[2],dim=0),
    torch.cosine_similarity(feat_45d[0],feat_bd[0],dim=0),
    torch.cosine_similarity(feat_45d[0],gtfeat,dim=0),
    torch.cosine_similarity(feat_bd[0],gtfeat,dim=0),
    torch.cosine_similarity(feat_bd[0],feat_45d[0],dim=0),
    ]
    print(aaa)



    # last_element=pcs_tensor[-1]
    # last_element=last_element.unsqueeze(0).repeat(expansion_n,1,1)
    # pcs_45d=torch.cat((pcs_tensor,last_element),dim=0)
    # print("pcs gen",torch.cuda.memory_allocated())
    # with torch.no_grad():
    #     net.eval()
    #     feat_45d=net(pcs_45d)
    # print("feat gen",torch.cuda.memory_allocated())
    # zero_e=torch.zeros([expansion_n]+list(pcs_tensor.shape[1:])).to(device)
    # pcs_45d0=torch.cat((pcs_tensor,zero_e),dim=0)
    # with torch.no_grad():
    #     net.eval()
    #     feat_45d0=net(pcs_45d0)        
    
    # feat_avg=torch.mean(feat_bd, dim=0)
    # feat_max=torch.max(feat_bd, dim=0).values
    # feat_avgmax=feat_avg+feat_max
    # feat_45d_avg=torch.mean(feat_45d, dim=0)
    # feat_45d_max=torch.max(feat_45d, dim=0).values 

    # feat_45d0_avg=torch.mean(feat_45d0, dim=0)
    # feat_45d0_max=torch.max(feat_45d0, dim=0).values

    
    
    # cls_id2feat_avg[int(cls_id)]=feat_avg
    # cls_id2feat_max[int(cls_id)]=feat_bd[0]
    # cls_id2feat_avgmax[int(cls_id)]=feat_avgmax        
    # cls_id2feat45d_avg[int(cls_id)]=feat_45d_avg
    # cls_id2feat45d_max[int(cls_id)]=feat_45d_max

    # cls_id2feat45d0_avg[int(cls_id)]=feat_45d0_avg
    # cls_id2feat45d0_max[int(cls_id)]=feat_45d0_max
    # del pcs_tensor
    # del last_element
    # del zero_e
    torch.cuda.empty_cache()





    # cls_id2feat_avg['feat_dim']=feat_avg.shape
    # cls_id2feat_max['feat_dim']=feat_max.shape
    # cls_id2feat45d_avg['feat_dim']=torch.Size([768])
    # cls_id2feat45d_max['feat_dim']=feat_45d_max.shape
    # cls_id2feat45d0_avg['feat_dim']=feat_45d0_avg.shape
    # cls_id2feat45d0_max['feat_dim']=feat_45d0_max.shape
    # cls_id2feat_avgmax['feat_dim']=torch.tensor(feat_avgmax.shape).to(feat_avgmax.device)
    # cls_id2feat_avgmax[999]=torch.tensor([9999])
    # feat_path = "cls_id2feat_avg.pkl"
    # with open(feat_path, 'wb') as cls_id2feat_avg_file:
    #     pickle.dump(cls_id2feat_avg, cls_id2feat_avg_file)

    feat_path = "cls_id2feat_max.pkl"
    with open(feat_path, 'wb') as cls_id2feat_max_file:
        pickle.dump(cls_id2feat_max, cls_id2feat_max_file)

    # feat_path = "cls_id2feat45d_avg.pkl"
    # with open(feat_path, 'wb') as cls_id2feat45d_avg_file:
    #     pickle.dump(cls_id2feat45d_avg, cls_id2feat45d_avg_file)
    # feat_path = "cls_id2feat45d_max.pkl"
    # with open(feat_path, 'wb') as cls_id2feat45d_max_file:
    #     pickle.dump(cls_id2feat45d_max, cls_id2feat45d_max_file)
    
    # feat_path = "cls_id2feat45d0_avg.pkl"
    # with open(feat_path, 'wb') as cls_id2feat45d0_avg_file:
    #     pickle.dump(cls_id2feat45d0_avg, cls_id2feat45d0_avg_file)
    # feat_path = "cls_id2feat45d0_max.pkl"
    # with open(feat_path, 'wb') as cls_id2feat45d0_max_file:
    #     pickle.dump(cls_id2feat45d0_max, cls_id2feat45d0_max_file)    

    # feat_path = "cls_id2feat_avgmax.pkl"
    # with open(feat_path, 'wb') as cls_id2feat_avgmax_file:
    #     pickle.dump(cls_id2feat_avgmax, cls_id2feat_avgmax_file)  




