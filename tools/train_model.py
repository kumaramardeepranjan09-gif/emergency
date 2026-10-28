#!/usr/bin/env python3
"""Train/evaluate a small logistic failure classifier with machine-separated splits.
Default data is SYNTHETIC and provides no evidence of real-world accuracy.
Real CSV columns: machine_id,temp_c,vibration_g,rotation_dps,used_hours,failed_next_hour
Each row must represent an independently labelled historical observation window.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ['temp_c','vibration_g','rotation_dps','used_hours']

def sigmoid(z):
    return 1/(1+math.exp(-max(-40,min(40,z))))

def synthetic():
    rng=random.Random(42)
    rows=[]
    for machine in range(100):
        wear=rng.random()*.3
        for window in range(24):
            age=window/2
            stress=rng.random()
            temp=24+stress*14+wear*4+rng.gauss(0,1.4)
            vib=max(0,.03+stress*.65+wear*.2+rng.gauss(0,.08))
            rot=max(0,stress*95+rng.gauss(0,14))
            # Synthetic probabilistic outcome; not a real failure experiment.
            latent=(temp-32)*.38+(vib-.3)*2+(rot-40)*.012+(age-5)*.20-1
            failed=int(rng.random()<sigmoid(latent))
            rows.append(dict(machine_id=f'synthetic-{machine:03}',temp_c=temp,vibration_g=vib,rotation_dps=rot,used_hours=age,failed_next_hour=failed))
    return rows

def read_rows(path):
    with path.open(newline='') as f:
        rows=list(csv.DictReader(f))
    for row in rows:
        if not row.get('machine_id'):
            raise ValueError('Every row needs a machine_id')
        for key in FEATURES:
            row[key]=float(row[key])
            if not math.isfinite(row[key]): raise ValueError(f'Invalid {key}')
        if str(row['failed_next_hour']) not in ('0','1'):raise ValueError('Labels must be 0 or 1')
        row['failed_next_hour']=int(row['failed_next_hour'])
    return rows

def evaluate(labels,probabilities):
    tp=sum(y==1 and p>=.5 for y,p in zip(labels,probabilities))
    tn=sum(y==0 and p<.5 for y,p in zip(labels,probabilities))
    fp=sum(y==0 and p>=.5 for y,p in zip(labels,probabilities))
    fn=sum(y==1 and p<.5 for y,p in zip(labels,probabilities))
    precision=tp/(tp+fp) if tp+fp else 0
    recall=tp/(tp+fn) if tp+fn else 0
    positives=[p for y,p in zip(labels,probabilities) if y]
    negatives=[p for y,p in zip(labels,probabilities) if not y]
    auc=sum((a>b)+.5*(a==b) for a in positives for b in negatives)/(len(positives)*len(negatives))
    return dict(accuracy=(tp+tn)/len(labels),precision=precision,recall=recall,f1=2*precision*recall/(precision+recall) if precision+recall else 0,roc_auc=auc,confusion_matrix={'tn':tn,'fp':fp,'fn':fn,'tp':tp},rows=len(labels),majority_baseline_accuracy=max(sum(labels),len(labels)-sum(labels))/len(labels))

def train(rows,epochs=600):
    ids=sorted({r['machine_id'] for r in rows})
    if len(ids)<10:raise ValueError('At least 10 separate machines required for grouped holdout')
    random.Random(7).shuffle(ids)
    cut=int(len(ids)*.8);train_ids=set(ids[:cut]);test_ids=set(ids[cut:])
    training=[r for r in rows if r['machine_id'] in train_ids]
    testing=[r for r in rows if r['machine_id'] in test_ids]
    for subset in (training,testing):
        if {r['failed_next_hour'] for r in subset}!={0,1}:raise ValueError('Both train and held-out machines need both outcome classes')
    mean=[sum(r[k] for r in training)/len(training) for k in FEATURES]
    std=[max(1e-8,math.sqrt(sum((r[k]-mean[i])**2 for r in training)/len(training))) for i,k in enumerate(FEATURES)]
    def features(row):return [1]+[(row[k]-mean[i])/std[i] for i,k in enumerate(FEATURES)]
    x=[features(r) for r in training];y=[r['failed_next_hour'] for r in training]
    weights=[0.0]*5
    for _ in range(epochs):
        grad=[0.0]*5
        for values,label in zip(x,y):
            error=sigmoid(sum(w*v for w,v in zip(weights,values)))-label
            for i in range(5):grad[i]+=error*values[i]
        weights=[w-.08*(g/len(x)+(.003*w if i else 0)) for i,(w,g) in enumerate(zip(weights,grad))]
    predictions=[sigmoid(sum(w*v for w,v in zip(weights,features(r)))) for r in testing]
    metrics=evaluate([r['failed_next_hour'] for r in testing],predictions)
    return dict(features=FEATURES,mean=mean,std=std,weights=weights,threshold=.5,metrics=metrics,split={'strategy':'80/20 grouped by machine_id; scaler fitted only on training set','train_machines':len(train_ids),'test_machines':len(test_ids),'train_rows':len(training),'test_rows':len(testing)},target='failure within the next hour',architecture='L2 logistic regression; 600 full-batch gradient steps',deployment='Research artifact only; never overrides firmware safety rules')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path)
    p.add_argument('--out',type=Path,default=ROOT/'docs/model-metrics.json')
    args=p.parse_args()
    model=train(read_rows(args.data) if args.data else synthetic())
    model['data_source']='user_supplied_historical_csv' if args.data else 'SYNTHETIC_DEMONSTRATION_ONLY'
    model['real_world_validated']=False
    model['limitations']='No claim of real-world accuracy, calibrated RUL, causal fault diagnosis or suitability for safety decisions. Audit label timing and failure windows before training on actual data.'
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(model,indent=2)+'\n')
    print(json.dumps({'data_source':model['data_source'],'metrics':model['metrics'],'output':str(args.out)},indent=2))
if __name__=='__main__':main()
