#!/bin/bash
# usage: run_m13_eval.sh <base|new> <ABSOLUTE outdir>   (config: /home/claude/work/cfg_m13_<mode>/repos.toml)
set -u
MODE=$1; OUT=$2; W=/home/claude/work; CFG=$W/cfg_m13_$MODE/repos.toml
source $W/venv/bin/activate; mkdir -p $OUT; cd $W/tc
if [ "$MODE" = base ]; then export PYTHONPATH=$W/m13/base031/src; else unset PYTHONPATH; fi
rm -rf $W/cfg_m13_$MODE/indexes
python -m token_context_mcp index --all --config $CFG --workers 2 > $OUT/index_all.json 2> $OUT/index_all.err
python evals/loc_eval.py --tasks evals/tasks/loc_token_context.json --repo-id tc-pinned --arm A1final --split heldout --config $CFG --max-tokens 8192 --limit 20 --expand none --output $OUT/loc_A1final.json > /dev/null 2>&1
python evals/loc_eval.py --tasks evals/tasks/loc_token_context.json --repo-id tc-pinned --arm A2 --split heldout --config $CFG --max-tokens 8192 --limit 20 --expand graph --output $OUT/loc_A2.json > /dev/null 2>&1
python evals/edge_eval.py --repo-id tc-pinned --config $CFG --tag $MODE --output $OUT/edge_eval.json > /dev/null 2>&1
for n in rich hono fastify csvhelper; do
  python evals/bench_retrieval.py --tasks evals/tasks/bench_$n.json --config $CFG --name $n --out-dir $OUT/bench_$n > $OUT/bench_$n.log 2>&1
  python evals/edge_audit.py --repo-id bench-$n --config $CFG --output $OUT/edge_audit_$n.json > /dev/null 2>&1
done
python evals/bench_retrieval.py --tasks evals/tasks/bench_jsoup.json --config $CFG --name jsoup --out-dir $OUT/bench_jsoup > $OUT/bench_jsoup.log 2>&1
python evals/edge_audit.py --repo-id dev-jsoup --config $CFG --output $OUT/edge_audit_jsoup.json > /dev/null 2>&1
python evals/bench_retrieval.py --tasks evals/tasks/heldout_serilog.json --config $CFG --name serilog --out-dir $OUT/bench_serilog > $OUT/bench_serilog.log 2>&1
python evals/edge_audit.py --repo-id heldout-serilog --config $CFG --output $OUT/edge_audit_serilog.json > /dev/null 2>&1
for n in hono fastify csvhelper; do
  python evals/edge_gold_eval.py --gold evals/tasks/edge_gold_$n.json --repo-id bench-$n --config $CFG --output $OUT/edge_gold_$n.json > /dev/null 2>&1
done
python evals/edge_gold_eval.py --gold evals/tasks/edge_gold_jsoup.json --repo-id dev-jsoup --config $CFG --output $OUT/edge_gold_jsoup.json > /dev/null 2>&1
python evals/edge_gold_eval.py --gold evals/tasks/edge_gold_heldout_serilog.json --repo-id heldout-serilog --config $CFG --output $OUT/edge_gold_serilog.json > /dev/null 2>&1
echo DONE > $OUT/DONE
