import sys
from pathlib import Path

# Add busan_apartment_analysis and area_master to sys.path
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
BUSAN_DIR = ROOT_DIR.parent / "busan_apartment_analysis"

sys.path.insert(0, str(BUSAN_DIR))
sys.path.insert(0, str(ROOT_DIR))

from src.market_cap_kb import run

if __name__ == "__main__":
    output = ROOT_DIR / "data" / "processed" / "market_cap" / "kb"
    adjustments = ROOT_DIR / "config" / "market_cap_kb_adjustments.json"
    transaction_master_output = output.parent / "market_cap_area_master.csv"
    print(f"Executing market_cap_kb.run with source={ROOT_DIR}, output={output} ...")
    result = run(
        source=ROOT_DIR,
        output=output,
        adjustments=adjustments,
        transaction_master_output=transaction_master_output,
        producer="area_master",
    )
    print("Execution finished successfully!")
    print(f"Run ID: {result.get('run_id')}")
    print(f"Targets: {result.get('targets')}, Complete: {result.get('complete')}, Adjusted Complete: {result.get('adjusted_complete')}")
