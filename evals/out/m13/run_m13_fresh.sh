#!/bin/bash
# usage: run_m13_fresh.sh <base|new> <ABSOLUTE outdir> ; fresh sets, measured once. Rule 17 guard with TC_GUARD_MILESTONE=m13
set -u
MODE=$1; OUT=$2; W=/home/claude/work; CFG=$W/cfg_m13f_$MODE/repos.toml; A=$W/m13/author_out
source $W/venv/bin/activate; mkdir -p $OUT; cd $W/tc
export TC_GUARD_MILESTONE=m13
FLAG=""
if [ "$MODE" = base ]; then export PYTHONPATH=$W/m13/base031/src; FLAG="--allow-baseline-code $W/m13/base031/src"; else unset PYTHONPATH; fi
rm -rf $W/cfg_m13f_$MODE/indexes
python -m token_context_mcp index --all --config $CFG --workers 2 > $OUT/index_all.json 2> $OUT/index_all.err
python evals/bench_retrieval.py --tasks $A/fresh_gson.json --config $CFG --name gson --role heldout $FLAG --out-dir $OUT/bench_gson > $OUT/bench_gson.log 2>&1
python evals/bench_retrieval.py --tasks $A/fresh_newtonsoft.json --config $CFG --name newtonsoft --role heldout $FLAG --out-dir $OUT/bench_newtonsoft > $OUT/bench_newtonsoft.log 2>&1
python evals/edge_gold_eval.py --gold $A/edge_gold_fresh_gson.json --repo-id fresh-gson --config $CFG --role heldout $FLAG --tag $MODE --output $OUT/edge_gold_gson.json > $OUT/eg_gson.log 2>&1
python evals/edge_gold_eval.py --gold $A/edge_gold_fresh_newtonsoft.json --repo-id fresh-newtonsoft --config $CFG --role heldout $FLAG --tag $MODE --output $OUT/edge_gold_newtonsoft.json > $OUT/eg_newtonsoft.log 2>&1
python evals/edge_audit.py --repo-id fresh-gson --config $CFG --output $OUT/edge_audit_gson.json > /dev/null 2>&1
python evals/edge_audit.py --repo-id fresh-newtonsoft --config $CFG --output $OUT/edge_audit_newtonsoft.json > /dev/null 2>&1
echo DONE > $OUT/DONE
