import csv
import os
import subprocess
import sys
import time

LEVELS = [
    (1, 1),
    (5, 5),
    (10, 5),
    (15, 5),
    (25, 5),
    (50, 10),
    (100, 20),
]

def run_locust_levels():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    locust_bin = os.path.join(base_dir, ".venv", "Scripts", "locust.exe")
    locust_file = os.path.join(base_dir, "loadtest", "locustfile.py")
    
    results = []

    for users, spawn_rate in LEVELS:
        csv_prefix = os.path.join(base_dir, "loadtest", f"results_{users}")
        print(f"\n=======================================================")
        print(f"RUNNING LOCUST BENCHMARK: {users} USERS (spawn rate: {spawn_rate})")
        print(f"=======================================================")
        
        cmd = [
            locust_bin,
            "-f", locust_file,
            "--headless",
            "-u", str(users),
            "-r", str(spawn_rate),
            "--run-time", "60s",
            "--host", "http://127.0.0.1:8000",
            "--csv", csv_prefix,
        ]
        
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True)
        dur = time.time() - t0
        print(f"Completed in {dur:.1f}s (returncode: {p.returncode})")
        if p.returncode != 0:
            print("STDERR:", p.stderr[:500])
        
        stats_csv = f"{csv_prefix}_stats.csv"
        if os.path.exists(stats_csv):
            rows_by_name = {}
            with open(stats_csv, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows_by_name[row.get("Name")] = row

            agg_row = rows_by_name.get("Aggregated", {})
            success_row = rows_by_name.get("Successful (2xx)", {})
            shed_row = rows_by_name.get("Backpressure (503 Shed)", {})
            other_row = rows_by_name.get("Other Errors", {})

            total_reqs = int(agg_row.get("Request Count", 0)) if agg_row else 0
            
            if success_row:
                s_count = int(success_row.get("Request Count", 0))
                p50 = float(success_row.get("50%", 0.0))
                p95 = float(success_row.get("95%", 0.0))
                rps = float(success_row.get("Requests/s", 0.0))
            else:
                s_count, p50, p95, rps = 0, 0.0, 0.0, 0.0

            shed_count = int(shed_row.get("Request Count", 0)) if shed_row else 0
            other_count = int(other_row.get("Request Count", 0)) if other_row else 0

            rec = {
                "users": users,
                "total_requests": total_reqs,
                "successful": s_count,
                "shed_503": shed_count,
                "other_errors": other_count,
                "p50_ms": p50,
                "p95_ms": p95,
                "req_per_sec": rps,
            }
            results.append(rec)
            print(f"Results for {users} users: {rec}")

    print("\n\n=======================================================")
    print("FINAL MEASURED LOAD TEST TABLE")
    print("=======================================================")
    print("| Concurrent Users | Total Requests | Successful (2xx) | 503 Shed | Other Errors | P50 Latency (2xx) | P95 Latency (2xx) | Successful Req/sec |")
    print("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in results:
        u_label = f"**{r['users']}** (baseline)" if r['users'] == 1 else f"**{r['users']}**"
        print(f"| {u_label} | {r['total_requests']:,} | {r['successful']:,} | {r['shed_503']:,} | {r['other_errors']} | {r['p50_ms']:.1f} ms | {r['p95_ms']:.1f} ms | {r['req_per_sec']:.2f} req/s |")

if __name__ == "__main__":
    run_locust_levels()
