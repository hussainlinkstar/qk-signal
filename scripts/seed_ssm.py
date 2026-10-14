import boto3, os, sys
ENV="/opt/docker/qiko-signal/.env"
PREFIX=os.getenv("SSM_PARAM_PREFIX", "/qiko-signal/")
SKIP={"SSM_ENABLED","SSM_OVERRIDE","SSM_PARAM_PREFIX","AWS_REGION","AWS_DEFAULT_REGION","GSM_ENABLED"}
ssm=boto3.client("ssm", region_name="eu-central-1")
seeded=skipped=0
for line in open(ENV):
    line=line.rstrip("\n")
    if not line or line.lstrip().startswith("#") or "=" not in line: continue
    k,_,v=line.partition("=")
    k=k.strip()
    v=v.strip()
    if len(v)>=2 and v[0]==v[-1] and v[0] in "\"'": v=v[1:-1]
    if not k or not v or k in SKIP: skipped+=1; continue
    try:
        ssm.put_parameter(Name=f"{PREFIX}{k}", Value=v, Type="SecureString", Overwrite=True)
        seeded+=1
    except Exception as e:
        print("ERR", k, str(e)[:80])
print(f"seeded={seeded} skipped(empty/ctrl)={skipped}")
# count
import itertools
p=ssm.get_paginator("get_parameters_by_path"); n=sum(len(pg.get("Parameters",[])) for pg in p.paginate(Path=PREFIX,Recursive=True))
print(f"params now under {PREFIX}:", n)
