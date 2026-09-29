import csv
import os
from database import add_energy_reading, DB_NAME

def import_energy_csv(file_path: str, db_path: str = DB_NAME) -> dict:
    """استيراد بيانات قراءات الطاقة من ملف CSV إلى قاعدة البيانات."""
    if not os.path.exists(file_path):
        return {"success": False, "error": f"File not found: {file_path}"}

    inserted_count = 0
    errors = []

    with open(file_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        
        # التأكد من مطابقة الحقول الأساسية للعقد المشترك
        expected_fields = {
            "timestamp", "building_id", "energy_kw", "hvac_kw", 
            "occupancy_pct", "solar_kw", "ev_kw", "temperature_c"
        }
        
        if not expected_fields.issubset(set(reader.fieldnames or [])):
            return {
                "success": False, 
                "error": f"CSV missing required columns. Expected: {expected_fields}"
            }

        for row_num, row in enumerate(reader, start=2):
            try:
                res = add_energy_reading(
                    timestamp=row["timestamp"].strip(),
                    building_id=row["building_id"].strip(),
                    energy_kw=float(row["energy_kw"]),
                    hvac_kw=float(row["hvac_kw"]),
                    occupancy_pct=float(row["occupancy_pct"]),
                    solar_kw=float(row["solar_kw"]),
                    ev_kw=float(row["ev_kw"]),
                    temperature_c=float(row["temperature_c"]),
                    db_path=db_path
                )
                if res["success"]:
                    inserted_count += 1
                else:
                    errors.append(f"Row {row_num}: {res.get('error')}")
            except (ValueError, KeyError) as e:
                errors.append(f"Row {row_num}: Data conversion error ({str(e)})")

    return {
        "success": True,
        "rows_imported": inserted_count,
        "errors_count": len(errors),
        "errors": errors[:5]  # عرض أول 5 أخطاء إن وجدت
    }

if __name__ == "__main__":
    sample_csv = "data/energy_sample.csv"
    if os.path.exists(sample_csv):
        result = import_energy_csv(sample_csv)
        print("Import result:", result)
    else:
        print(f"Ready for Person 1 CSV data at: {sample_csv}")