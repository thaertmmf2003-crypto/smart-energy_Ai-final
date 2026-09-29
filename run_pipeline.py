"""
Smart Energy AI - End-to-End Pipeline Runner

Runs:
1. Data validation
2. ML dataset preparation
3. Energy forecasting
4. Prediction engine
5. Digital twin simulation
6. Action optimization
7. Action verification
"""

from pathlib import Path
import subprocess
import sys
import time

BASE_DIR = Path(__file__).resolve().parent


PIPELINE = [
    {
        "name": "Data Validation",
        "file": "tests/test_data.py",
    },
    {
        "name": "ML Dataset Preparation",
        "file": "prepare_ml_data.py",
    },
    {
        "name": "Energy Forecast Model",
        "file": "ml_models.py",
    },
    {
        "name": "Prediction Engine",
        "file": "prediction_engine.py",
    },
    {
        "name": "Digital Twin Simulator",
        "file": "simulator.py",
    },
    {
        "name": "Action Optimizer",
        "file": "optimizer.py",
    },
    {
        "name": "Action Verification",
        "file": "verification.py",
    },
]


def run_step(step_number, step):

    name = step["name"]

    script_path = BASE_DIR / step["file"]

    print("\n" + "=" * 70)

    print(f"STEP {step_number}/{len(PIPELINE)}" f" - {name}")

    print("=" * 70)

    if not script_path.exists():

        print(f"[FAIL] File not found:" f" {script_path}")

        return False, 0

    start_time = time.time()

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
        ],
        cwd=BASE_DIR,
    )

    elapsed = time.time() - start_time

    if result.returncode != 0:

        print(f"\n[FAIL] {name}")

        print(f"Exit code:" f" {result.returncode}")

        return False, elapsed

    print(f"\n[PASS] {name}" f" ({elapsed:.2f} seconds)")

    return True, elapsed


def main():

    print("=" * 70)
    print("SMART ENERGY AI - END-TO-END PIPELINE")
    print("=" * 70)

    pipeline_start = time.time()

    results = []

    for index, step in enumerate(
        PIPELINE,
        start=1,
    ):

        success, elapsed = run_step(
            index,
            step,
        )

        results.append(
            {
                "name": step["name"],
                "success": success,
                "time": elapsed,
            }
        )

        if not success:

            print("\n" + "=" * 70)

            print("PIPELINE STOPPED")

            print(f"Failed step:" f" {step['name']}")

            print("=" * 70)

            sys.exit(1)

    total_time = time.time() - pipeline_start

    # -----------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------

    print("\n" + "=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)

    for result in results:

        status = "PASS" if result["success"] else "FAIL"

        print(f"[{status}] " f"{result['name']:<30}" f"{result['time']:.2f} sec")

    print("-" * 70)

    print(f"Total execution time:" f" {total_time:.2f} seconds")

    print("\n" + "=" * 70)

    print("SMART ENERGY AI PIPELINE PASSED")

    print("=" * 70)


if __name__ == "__main__":
    main()
