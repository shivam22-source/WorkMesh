import json


def show(p):
    d = json.load(open(p))
    print('FILE:', p)
    for strat in ['lexical_only', 'lexical_and', 'vector_only', 'hybrid_rrf', 'hybrid_plus_graph']:
        v = d['strategies'][strat]
        print(f"\nSTRATEGY: {strat}")
        if 'dev_60' in v:
            dev = v['dev_60']
            print(f"  [dev_60] count={dev['count']}")
            print(f"    R@1: {dev['recall_at_1']['mean']*100:.1f}%")
            print(f"    R@5: {dev['recall_at_5']['mean']*100:.1f}% [{dev['recall_at_5']['ci_low']*100:.1f}%, {dev['recall_at_5']['ci_high']*100:.1f}%]")
            print(f"    MRR: {dev['mrr']['mean']:.4f} [{dev['mrr']['ci_low']:.4f}, {dev['mrr']['ci_high']:.4f}]")
            print(f"    nDCG@10: {dev['ndcg_at_10']['mean']:.4f} [{dev['ndcg_at_10']['ci_low']:.4f}, {dev['ndcg_at_10']['ci_high']:.4f}]")
            print(f"    p50/p95: {dev['latency_ms']['p50']:.1f} / {dev['latency_ms']['p95']:.1f} ms")
            print(f"    denied leaks: {v.get('denied_identity_leaks')} (rate: {v.get('denied_identity_leak_rate', 0.0)*100:.1f}%)")
        o = v['overall']
        print(f"  [overall] count={o['count']}")
        print(f"    R@1: {o['recall_at_1']['mean']*100:.1f}%")
        print(f"    R@5: {o['recall_at_5']['mean']*100:.1f}% [{o['recall_at_5']['ci_low']*100:.1f}%, {o['recall_at_5']['ci_high']*100:.1f}%]")
        print(f"    MRR: {o['mrr']['mean']:.4f} [{o['mrr']['ci_low']:.4f}, {o['mrr']['ci_high']:.4f}]")
        print(f"    nDCG@10: {o['ndcg_at_10']['mean']:.4f} [{o['ndcg_at_10']['ci_low']:.4f}, {o['ndcg_at_10']['ci_high']:.4f}]")
        print(f"    p50/p95: {o['latency_ms']['p50']:.1f} / {o['latency_ms']['p95']:.1f} ms")
        
        print("  Categories:")
        for cat, cv in v.get('by_category', {}).items():
            print(f"    - {cat:18s}: count={cv['count']}, R@5={cv['recall_at_5']['mean']*100:5.1f}%, nDCG@10={cv['ndcg_at_10']['mean']:6.4f}")

if __name__ == '__main__':
    show('data/evaluation/results/ablation_v2_results.json')
    print('='*70)
    show('data/evaluation/results/heldout_v2_results.json')
