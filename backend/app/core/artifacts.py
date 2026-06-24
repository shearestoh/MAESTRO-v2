"""Export helpers — CSV, JSON, campaign spec."""
import csv, io, json, tempfile
from typing import List


def export_results_csv_bytes(results_store: List[dict]) -> bytes:
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["power_W", "step", "active_material", "porosity", "specific_energy"])
    for r in results_store:
        for i, (xy, e) in enumerate(zip(r.get("X", []), r.get("y", []))):
            w.writerow([r["power_W"], i + 1, xy[0], xy[1], e])
    return out.getvalue().encode()


def export_results_json_bytes(results_store: List[dict]) -> bytes:
    return json.dumps(results_store, indent=2).encode()


def export_campaign_json_bytes(campaign_dict) -> bytes:
    return json.dumps(campaign_dict or {}, indent=2).encode()


def save_bytes_to_tempfile(data: bytes, suffix: str, prefix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=prefix)
    tmp.write(data); tmp.flush(); tmp.close()
    return tmp.name