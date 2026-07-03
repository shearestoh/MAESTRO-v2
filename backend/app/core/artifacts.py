"""
Export helpers — CSV, JSON, campaign spec.
"""
import csv
import io
import json
import tempfile
from typing import List


def export_results_csv_bytes(results_store: List[dict]) -> bytes:
    out = io.StringIO()
    w   = csv.writer(out)

    if not results_store:
        w.writerow(["condition_label", "condition_value", "step", "objective"])
        return out.getvalue().encode()

    first       = results_store[0]
    param_names = first.get("param_names", [])
    headers     = ["condition_label", "condition_value", "step"] + param_names + ["objective"]
    w.writerow(headers)

    for r in results_store:
        cond_label  = r.get("condition_label", "condition")
        cond_value  = r.get("condition_value", 0)
        pnames      = r.get("param_names", param_names)
        for i, (xy, e) in enumerate(zip(r.get("X", []), r.get("y", []))):
            row = [cond_label, cond_value, i + 1]
            for j in range(len(pnames)):
                row.append(xy[j] if j < len(xy) else "")
            row.append(e)
            w.writerow(row)

    return out.getvalue().encode()


def export_results_json_bytes(results_store: List[dict]) -> bytes:
    return json.dumps(results_store, indent=2).encode()


def export_campaign_json_bytes(campaign_dict) -> bytes:
    return json.dumps(campaign_dict or {}, indent=2).encode()


def save_bytes_to_tempfile(data: bytes, suffix: str, prefix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=prefix)
    tmp.write(data)
    tmp.flush()
    tmp.close()
    return tmp.name