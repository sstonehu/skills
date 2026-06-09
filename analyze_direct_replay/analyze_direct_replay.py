#!/usr/bin/env python3
"""
Analyze RouterProxyV8Direct direct replay snapshots.

The script intentionally uses only the Python standard library so it can be
copied with the skill and run from any workspace checkout.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TEST_OUTPUT_MARKER = f"{os.sep}test_output{os.sep}"

SELECTORS = {
    "0x0ab35bb0": "duralTradeFromWETH(bytes)",
    "0x2e6940e9": "loanTrade(bytes)",
}

CUSTOM_ERRORS = {
    "0xe39aafee": "NoProfit()",
    "0x7005668f": "TradeFailed(uint256)",
    "0xdd85b49d": "InvalidDexType(uint8)",
    "0x0453a8bb": "InvalidExactOutputDex(uint8)",
    "0x28393780": "InvalidFlashLoanSender(address)",
    "0x08c379a0": "Error(string)",
}

STEP_NAMES = {
    0x02: "v2_family",
    0x03: "v3_family",
    0x04: "smarDex",
    0x05: "curveV2",
    0x06: "balancer_family",
    0x07: "multiV4",
    0x08: "multiCore",
    0x09: "multiCoreV3",
    0x0A: "balancerV3_multi",
    0x10: "1inch_limit_order",
    0x11: "uniX_limit_order",
    0x12: "v2_with_args",
    0x50: "wrap_family",
    0x51: "fwWrap",
    0x52: "dodoV2",
    0x53: "origin_family",
    0x54: "relayV2_family",
    0x55: "syrupMigrator",
    0x56: "ohm_family",
    0x57: "pWrap",
    0x58: "goldx",
    0x59: "sWrap",
    0x63: "aaveV3",
    0x64: "bancorV2",
    0x65: "fluid_family",
    0x67: "algebraIntegral",
    0xFF: "control",
}

CONTROL_STEPS = {
    "ff0100": ("transfer", 63),
    "ff0200": ("approve", 44),
    "ff0300": ("permit", 44),
    "ff0600": ("depositWETH", 23),
    "ff0700": ("guard_or_redeem", 23),
    "ff0800": ("guard_or_redeem", 23),
}


@dataclass
class Step:
    idx: int
    offset: int
    length: int
    tag: str
    name: str
    semantic: str
    addresses: list[str] = field(default_factory=list)
    raw: str = ""


@dataclass
class DecodeResult:
    selector: str = ""
    method: str = "unknown"
    payload_len_declared: int | None = None
    payload_len_actual: int = 0
    payload_offset: int | None = None
    loan_prefix: dict[str, str] | None = None
    steps: list[Step] = field(default_factory=list)
    trailer: str = ""
    mismatch: str = ""


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def strip_0x(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith(("0x", "0X")):
        return value[2:]
    return value


def hex_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return 0
        try:
            return int(s, 16) if s.startswith(("0x", "0X")) else int(s)
        except ValueError:
            return 0
    return 0


def addr_from(raw: str, start_byte: int) -> str:
    start = start_byte * 2
    end = start + 40
    if end > len(raw):
        return ""
    return "0x" + raw[start:end].lower()


def u20(raw: str, start_byte: int) -> str:
    start = start_byte * 2
    end = start + 40
    if end > len(raw):
        return ""
    return "0x" + raw[start:end]


def norm_addr(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    s = value.lower()
    if re.fullmatch(r"0x[0-9a-f]{40}", s):
        return s
    return ""


def decode_outer(calldata: str) -> tuple[str, int | None, int | None, str, str]:
    data = strip_0x(calldata)
    if len(data) < 8:
        return "0x" + data, None, None, "", "calldata shorter than selector"
    selector = "0x" + data[:8]
    if len(data) < 136:
        return selector, None, None, "", "calldata shorter than abi bytes header"
    offset = int(data[8:72], 16)
    length = int(data[72:136], 16)
    start = 8 + offset * 2 + 64
    payload = data[start : start + length * 2]
    if len(payload) < length * 2:
        return selector, offset, length, payload, "payload shorter than abi length"
    return selector, offset, length, payload, ""


def decode_steps(calldata: str) -> DecodeResult:
    selector, offset, declared_len, payload, mismatch = decode_outer(calldata)
    result = DecodeResult(
        selector=selector,
        method=SELECTORS.get(selector, "unknown"),
        payload_len_declared=declared_len,
        payload_len_actual=len(payload) // 2,
        payload_offset=offset,
        mismatch=mismatch,
    )
    if mismatch:
        return result

    pos = 0
    if selector == "0x2e6940e9" and len(payload) >= 80:
        result.loan_prefix = {
            "loanAmount": "0x" + payload[:40],
            "loanToken": "0x" + payload[40:80].lower(),
        }
        pos = 40

    idx = 0
    while pos < len(payload) // 2:
        remaining = len(payload) // 2 - pos
        if remaining == 5 and payload[pos * 2 : pos * 2 + 2] == "ff":
            result.trailer = "0x" + payload[pos * 2 :]
            break
        if remaining < 3:
            result.mismatch = f"decode_mismatch: short header at byte {pos}"
            break

        tag = payload[pos * 2 : pos * 2 + 6].lower()
        header = int(tag[:2], 16)
        dex_type = int(tag[2:4], 16)
        length, name, semantic = step_length_and_name(payload, pos, tag, header, dex_type)
        if length <= 0:
            result.mismatch = f"decode_mismatch: unknown step tag 0x{tag} at byte {pos}"
            break
        if pos + length > len(payload) // 2:
            result.mismatch = f"decode_mismatch: step 0x{tag} overruns payload at byte {pos}"
            break

        raw = payload[pos * 2 : (pos + length) * 2]
        step = Step(
            idx=idx,
            offset=pos,
            length=length,
            tag="0x" + tag,
            name=name,
            semantic=semantic,
            addresses=step_addresses(raw, header, dex_type),
            raw="0x" + raw,
        )
        result.steps.append(step)
        pos += length
        idx += 1

    return result


def step_length_and_name(payload: str, pos: int, tag: str, header: int, dex_type: int) -> tuple[int, str, str]:
    if tag in CONTROL_STEPS:
        name, length = CONTROL_STEPS[tag]
        return length, name, name
    if header == 0xFF:
        return 0, "unknown_control", "unknown_control"

    name = STEP_NAMES.get(header, f"dex_0x{header:02x}")
    if header in (0x03, 0x04):
        return 83, name, "amount,pool,recipient,bound"
    if header == 0x02:
        if dex_type in range(0x00, 0x21):
            return 64, name, "amountOut,pool,recipient,token0In"
        if dex_type == 0x21:
            return 103, name, "amountIn,pool,tokenIn,tokenOut,bound"
        if dex_type == 0x22:
            return 84, name, "amountIn,pool,recipient,isETHIn,bound"
    if header == 0x12:
        return 84, name, "amountOut,pool,recipient,token0In,tokenOut"
    if header == 0x05:
        return 85, name, "curveFlags,amountIn,pool,recipient,bound"
    if header == 0x06:
        if dex_type == 0x00:
            return 135, "balancerV2", "amount,recipient,tokenIn,tokenOut,poolId,bound"
        if dex_type == 0x01:
            return 103, "BPT", "amount,pool,tokenIn,tokenOut,bound"
        if dex_type == 0x02:
            return 123, "balancerV3", "amount,recipient,tokenIn,tokenOut,pool,hook"
        return 103, "balancer_family", "amount,poolOrRecipient,tokenIn,tokenOut,boundOrHook"
    if header in (0x07, 0x08, 0x09, 0x0A):
        if dex_type == 0x02:
            return 43, name, "settle amount,token"
        pool_len_byte = pos + 23
        if pool_len_byte * 2 + 2 > len(payload):
            return 0, name, "missing_pool_length"
        pool_count = int(payload[pool_len_byte * 2 : pool_len_byte * 2 + 2], 16)
        per_pool = 46 if header == 0x07 else 52 if header in (0x08, 0x09) else 60
        return 84 + pool_count * per_pool, name, f"multi_pool_count={pool_count}"
    if header == 0x10:
        return 343, name, "amountIn,recipient,order"
    if header == 0x11:
        return 772, name, "encodedOrder,signature"
    if header == 0x50:
        if dex_type == 0x01:
            return 43, name, "amountIn,pool"
        if dex_type == 0x02:
            return 63, name, "amountIn,pool,recipient"
    if header == 0x51:
        return 63, name, "amountIn,pool,recipient"
    if header == 0x52:
        return 63, name, "pool,recipient,bound"
    if header == 0x53:
        if dex_type == 0x03:
            return 103, name, "amountIn,pool,tokenIn,tokenOut,recipient"
        return 63, name, "amountIn,pool,tokenIn"
    if header == 0x54:
        if dex_type == 0x02:
            return 83, name, "amountIn,tokenIn,amountOut,tokenOut"
        return 43, name, "amountIn,tokenIn"
    if header == 0x55 and dex_type == 0x01:
        return 63, name, "amountIn,pool,recipient"
    if header == 0x56:
        if dex_type == 0x01:
            return 65, name, "amountIn,pool,recipient,i,j"
        if dex_type == 0x02:
            return 45, name, "amountIn,pool,i,j"
    if header in (0x57, 0x58, 0x59):
        return 63, name, "amount,pool,recipient_or_tokenIn"
    if header == 0x63:
        return 83, name, "amountIn,pool,recipient,underlying"
    if header == 0x64:
        return 144, name, "amountIn,pool0,pool1,recipient,tokenIn,tokenOut,isETHIn,bound"
    if header == 0x65:
        if dex_type == 0x01:
            return 156, name, "fluidDexLite amountIn,pool,recipient,isETHIn,tokens,salt,bound"
        return 84, name, "fluid amountIn,pool,recipient,isETHIn,bound"
    if header == 0x67:
        return 123, name, "amountIn,recipient,tokenIn,deployer,tokenOut,bound"
    return 0, name, "unknown"


def step_addresses(raw: str, header: int, dex_type: int) -> list[str]:
    addrs: list[str] = []

    def add(offset: int) -> None:
        value = addr_from(raw, offset)
        if value and value != "0x0000000000000000000000000000000000000000":
            addrs.append(value)

    if header in (0x03, 0x04):
        add(23)
        add(43)
    elif header == 0x02:
        add(23)
        add(43)
        if dex_type == 0x21:
            add(63)
    elif header == 0x12:
        add(23)
        add(43)
        add(64)
    elif header == 0x05:
        add(25)
        add(45)
    elif header == 0x06:
        if dex_type == 0x00:
            add(23)
            add(43)
            add(63)
        else:
            add(23)
            add(43)
            add(63)
            add(83)
    elif header in (0x07, 0x08, 0x09, 0x0A):
        if dex_type == 0x02:
            add(23)
            return sorted(set(addrs))
        add(3)
        add(44)
        pool_count = int(raw[46:48], 16) if len(raw) >= 48 else 0
        per_pool = 46 if header == 0x07 else 52 if header in (0x08, 0x09) else 60
        base = 64
        for i in range(pool_count):
            p = base + i * per_pool
            if header == 0x07:
                add(p + 6)
                add(p + 26)
            elif header in (0x08, 0x09):
                add(p + 32)
            else:
                add(p)
                add(p + 20)
                add(p + 40)
    elif header == 0x10:
        add(23)
    elif header == 0x50:
        add(23)
        if dex_type == 0x02:
            add(43)
    elif header in (0x51, 0x55, 0x58, 0x59):
        add(23)
        add(43)
    elif header == 0x52:
        add(3)
        add(23)
    elif header == 0x53:
        add(23)
        add(43)
        if dex_type == 0x03:
            add(63)
            add(83)
    elif header == 0x54:
        add(23)
        if dex_type == 0x02:
            add(63)
    elif header == 0x56:
        add(23)
        if dex_type == 0x01:
            add(43)
    elif header == 0x57:
        add(23)
        add(43)
    elif header == 0x63:
        add(23)
        add(43)
        add(63)
    elif header == 0x64:
        add(23)
        add(43)
        add(63)
        add(83)
        add(103)
    elif header == 0x65:
        add(23)
        add(43)
        if dex_type == 0x01:
            add(64)
            add(84)
    elif header == 0x67:
        add(23)
        add(43)
        add(63)
        add(83)
    elif header == 0xFF:
        if raw.startswith(("ff0100", "ff0200", "ff0300")):
            add(3)
            add(23)
    return sorted(set(addrs))


def has_error(node: Any) -> bool:
    return isinstance(node, dict) and bool(node.get("error"))


def deepest_error(node: Any, path: str = "root") -> tuple[dict[str, Any] | None, str]:
    if not isinstance(node, dict):
        return None, path
    best = (node, path) if node.get("error") else (None, path)
    for i, child in enumerate(as_list(node.get("calls"))):
        child_best, child_path = deepest_error(child, f"{path}.calls[{i}]")
        if child_best is not None:
            best = (child_best, child_path)
    return best


def output_selector(output: Any) -> str:
    data = strip_0x(output)
    if len(data) >= 8:
        return "0x" + data[:8].lower()
    return ""


def decode_error_string(output: Any) -> str:
    data = strip_0x(output)
    if not data.startswith("08c379a0") or len(data) < 8 + 64 + 64:
        return ""
    try:
        strlen = int(data[8 + 64 : 8 + 128], 16)
        raw = data[8 + 128 : 8 + 128 + strlen * 2]
        return bytes.fromhex(raw).decode("utf-8", errors="replace")
    except Exception:
        return ""


def classify_revert(trace: dict[str, Any], decoded: DecodeResult) -> dict[str, Any]:
    root_error = bool(trace.get("error"))
    err_node, err_path = deepest_error(trace)
    if err_node is None and not root_error:
        return {"is_revert": False, "root_cause": "success", "trace_error_path": ""}

    if err_node is trace and not any(has_error(c) for c in as_list(trace.get("calls"))):
        err_path = "root_only"

    selector = output_selector((err_node or trace).get("output"))
    custom = CUSTOM_ERRORS.get(selector, "")
    reason = (err_node or {}).get("revertReason") or decode_error_string((err_node or trace).get("output"))

    matched_step = match_step(err_node or trace, decoded)
    if err_path == "root_only" and custom:
        root_cause = f"post_check_{custom}"
    elif custom:
        root_cause = custom
    elif reason:
        root_cause = reason
    elif selector:
        root_cause = f"selector_{selector}"
    else:
        root_cause = "root_unknown" if err_path == "root_only" else "trace_revert"

    return {
        "is_revert": True,
        "root_cause": root_cause,
        "custom_error": custom,
        "output_selector": selector,
        "trace_error_path": err_path,
        "error_to": norm_addr((err_node or {}).get("to")),
        "error_selector": output_selector((err_node or {}).get("input")),
        "revert_reason": reason,
        "step": matched_step,
    }


def match_step(err_node: dict[str, Any], decoded: DecodeResult) -> Step | None:
    target = norm_addr(err_node.get("to"))
    if target:
        for step in reversed(decoded.steps):
            if target in step.addresses:
                return step
    selector = output_selector(err_node.get("input"))
    if selector == "0x022c0d9f":
        for step in reversed(decoded.steps):
            if step.name in ("v2_family", "v2_with_args"):
                return step
    if selector in ("0x128acb08", "0xf3cd914c"):
        for step in reversed(decoded.steps):
            if step.name in ("v3_family", "smarDex", "fluid_family", "algebraIntegral"):
                return step
    return decoded.steps[-1] if decoded.steps else None


def response_success(resp: dict[str, Any]) -> bool:
    result = resp.get("result") if isinstance(resp, dict) else None
    return isinstance(result, dict) and not result.get("error")


def item_success_from_mid1(item: dict[str, Any], key: str) -> bool:
    if not isinstance(item, dict):
        return False
    if key in item:
        return hex_int(item.get(key)) > 0
    return False


def find_batch_inputs(inputs: list[str]) -> tuple[Path, list[Path]]:
    paths = [Path(p).resolve() for p in inputs]
    if not paths:
        raise SystemExit("usage error: provide a batch dir or one or more *_direct_resps.json files")
    if len(paths) == 1 and paths[0].is_dir():
        batch_dir = paths[0]
        snapshot_dir = batch_dir / "go_replay_snapshots"
        search_dir = snapshot_dir if snapshot_dir.is_dir() else batch_dir
        resps = sorted(search_dir.glob("*_direct_resps.json"))
        if not resps:
            resps = sorted(search_dir.glob("*_direct_resp.json"))
        return batch_dir, resps
    resps = []
    for path in paths:
        if path.is_dir():
            resps.extend(sorted(path.glob("*_direct_resps.json")))
        elif path.name.endswith(("_direct_resps.json", "_direct_resp.json")):
            resps.append(path)
    if not resps:
        raise SystemExit("no *_direct_resps.json files found")
    batch_dir = common_batch_dir(resps)
    return batch_dir, sorted(set(resps))


def common_batch_dir(resps: list[Path]) -> Path:
    parent = Path(os.path.commonpath([str(p.parent) for p in resps]))
    if parent.name == "go_replay_snapshots":
        return parent.parent
    return parent


def companion(path: Path, suffix: str) -> Path:
    name = path.name
    for old in ("_direct_resps.json", "_direct_resp.json"):
        if name.endswith(old):
            return path.with_name(name[: -len(old)] + suffix)
    return path.with_name(name + suffix)


def load_replay_rows(batch_dir: Path) -> list[dict[str, Any]]:
    result_json = batch_dir / "replay_result.json"
    if result_json.exists():
        rows = load_json(result_json)
        return as_list(rows)
    csvs = sorted(batch_dir.glob("replay_result_*.csv"))
    if not csvs:
        return []
    with csvs[-1].open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def rel_test_output(path: Path) -> str:
    s = str(path.resolve())
    marker = TEST_OUTPUT_MARKER
    if marker in s:
        return s.split(marker, 1)[1]
    return os.path.relpath(s, ROOT)


def tx_hash_from(row: dict[str, Any], fallback_name: str) -> str:
    for key in ("txHash", "hash", "Hash", "tx"):
        value = row.get(key)
        if isinstance(value, str) and value.startswith("0x"):
            return value
    m = re.search(r"opportunity\.replay\.([0-9a-fA-F]+)", fallback_name)
    if m:
        return m.group(1)
    return ""


def tx_short_from_name(name: str) -> str:
    m = re.search(r"opportunity\.replay\.([0-9a-fA-F]+)", name)
    return m.group(1).lower() if m else ""


def percent(num: int, den: int) -> str:
    if den <= 0:
        return "0.00%"
    return f"{num * 100 / den:.2f}%"


def row_int(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def analyze(batch_dir: Path, resps_paths: list[Path], write_report: bool, output: Path | None) -> dict[str, Any]:
    replay_rows = load_replay_rows(batch_dir)
    replay_tx_by_short = {}
    for row in replay_rows:
        tx = tx_hash_from(row, "")
        if tx.startswith("0x"):
            replay_tx_by_short[tx[2:10].lower()] = tx
    details: list[dict[str, Any]] = []
    counters = {
        "step_idx": Counter(),
        "step_tag": Counter(),
        "root_cause": Counter(),
        "custom_error": Counter(),
        "root_only": Counter(),
    }

    totals = defaultdict(int)
    totals["txn_count"] = len(replay_rows) if replay_rows else len({p.stem.split("_", 1)[0] for p in resps_paths})
    files_seen = 0
    direct_success_txn = 0

    for resps_path in resps_paths:
        files_seen += 1
        reqs_path = companion(resps_path, "_direct_reqs.json")
        mid1_path = companion(resps_path, "_mid1_Revenue.json")
        reqs = as_list(load_json(reqs_path)) if reqs_path.exists() else []
        resps = as_list(load_json(resps_path))
        mid1 = as_list(load_json(mid1_path)) if mid1_path.exists() else []
        req_by_id = {str(x.get("id")): x for x in reqs if isinstance(x, dict) and "id" in x}
        mid1_by_id = {str(i): item for i, item in enumerate(mid1)}

        totals["direct_req_total"] += len(reqs)
        totals["direct_resp_total"] += len(resps)
        totals["mid1_item_count"] += len(mid1)
        totals["dynamic_success_item"] += sum(1 for item in mid1 if item_success_from_mid1(item, "GasUsedDynamic"))
        totals["direct_success_item_mid1"] += sum(1 for item in mid1 if item_success_from_mid1(item, "GasUsedDirect"))
        if mid1:
            totals["mid1_txn_count"] += 1
        if any(response_success(resp) for resp in resps):
            direct_success_txn += 1

        for resp_index, resp in enumerate(resps):
            if not isinstance(resp, dict) or not isinstance(resp.get("result"), dict):
                continue
            trace = resp["result"]
            decoded = decode_steps(trace.get("input", ""))
            cls = classify_revert(trace, decoded)
            if not cls["is_revert"]:
                totals["direct_success_item_resp"] += 1
                continue

            totals["direct_revert_total"] += 1
            step = cls.get("step")
            step_idx = step.idx if isinstance(step, Step) else None
            step_tag = step.tag if isinstance(step, Step) else "post_check"
            step_name = step.name if isinstance(step, Step) else "post_check"
            semantic = step.semantic if isinstance(step, Step) else cls["root_cause"]

            counters["step_idx"][str(step_idx) if step_idx is not None else "post_check"] += 1
            counters["step_tag"][f"{step_tag} {step_name} | {semantic}"] += 1
            counters["root_cause"][cls["root_cause"]] += 1
            if cls.get("custom_error"):
                counters["custom_error"][cls["custom_error"]] += 1
            if cls.get("trace_error_path") == "root_only":
                counters["root_only"][cls["root_cause"]] += 1

            rid = resp.get("id", resp_index)
            mid1_item = mid1_by_id.get(str(rid), mid1[resp_index] if resp_index < len(mid1) else {})
            tx_short = tx_short_from_name(resps_path.name)
            tx_hash = replay_tx_by_short.get(tx_short) or tx_hash_from(
                mid1_item if isinstance(mid1_item, dict) else {}, resps_path.name
            )
            details.append(
                {
                    "resp_index": resp_index,
                    "id": rid,
                    "txHash": tx_hash,
                    "step_idx": step_idx,
                    "step_tag": step_tag,
                    "step_name": step_name,
                    "semantic": semantic,
                    "root_cause": cls["root_cause"],
                    "custom_error": cls.get("custom_error", ""),
                    "trace_error_path": cls.get("trace_error_path", ""),
                    "error_to": cls.get("error_to", ""),
                    "error_selector": cls.get("error_selector", ""),
                    "revert_reason": cls.get("revert_reason", ""),
                    "reqs_file": rel_test_output(reqs_path),
                    "resps_file": rel_test_output(resps_path),
                    "mid1_file": rel_test_output(mid1_path),
                    "DuralPathIdx": mid1_item.get("DuralPathIdx", "") if isinstance(mid1_item, dict) else "",
                    "calldata": decoded_to_text(decoded),
                    "decode_mismatch": decoded.mismatch,
                    "request_found": str(rid) in req_by_id,
                }
            )

    has_replay_direct = any("directSuccessCount" in row for row in replay_rows)
    has_replay_dynamic = any("dynamicSuccessCount" in row for row in replay_rows)
    has_replay_mid1_items = any("mid1RevenueSuccessCount" in row for row in replay_rows)

    if has_replay_direct:
        totals["direct_success_txn"] = sum(1 for row in replay_rows if row_int(row, "directSuccessCount") > 0)
        totals["direct_success_item"] = sum(row_int(row, "directSuccessCount") for row in replay_rows)
    else:
        totals["direct_success_txn"] = direct_success_txn
        totals["direct_success_item"] = totals["direct_success_item_resp"] or totals["direct_success_item_mid1"]

    if has_replay_dynamic:
        totals["dynamic_success_item"] = sum(row_int(row, "dynamicSuccessCount") for row in replay_rows)
    if has_replay_mid1_items:
        totals["mid1_item_count"] = sum(row_int(row, "mid1RevenueSuccessCount") for row in replay_rows)
        totals["mid1_txn_count"] = sum(
            1
            for row in replay_rows
            if row.get("mid1Produced") == "Y" or row_int(row, "mid1RevenueSuccessCount") > 0
        )
    summary = {
        "batch_dir": str(batch_dir),
        "sample_range": rel_test_output(batch_dir),
        "files_seen": files_seen,
        "totals": dict(totals),
        "distributions": {k: dict(v.most_common()) for k, v in counters.items()},
        "details": details,
    }

    report_path = output or batch_dir / "direct_fail_report.md"
    if write_report:
        report_path.write_text(render_report(summary), encoding="utf-8")
        summary["report_path"] = str(report_path)
    return summary


def decoded_to_text(decoded: DecodeResult) -> str:
    lines = [
        f"selector={decoded.selector} method={decoded.method}",
        f"offset={decoded.payload_offset} payload_len={decoded.payload_len_declared}/{decoded.payload_len_actual}",
    ]
    if decoded.loan_prefix:
        lines.append(f"loanAmount={decoded.loan_prefix['loanAmount']} loanToken={decoded.loan_prefix['loanToken']}")
    for step in decoded.steps:
        addr_text = ",".join(step.addresses[:4])
        lines.append(
            f"#{step.idx} byte={step.offset} len={step.length} {step.tag} {step.name} {step.semantic}"
            + (f" addrs={addr_text}" if addr_text else "")
        )
    if decoded.trailer:
        lines.append(f"trailer={decoded.trailer}")
    if decoded.mismatch:
        lines.append(decoded.mismatch)
    return "\n".join(lines)


def render_counter(counter: dict[str, int]) -> str:
    if not counter:
        return "- 无"
    return "\n".join(f"- {key}: {value}" for key, value in counter.items())


def render_report(summary: dict[str, Any]) -> str:
    totals = summary["totals"]
    d = summary["distributions"]
    details = summary["details"]
    lines = [
        "# Direct Fail Report",
        "",
        f"- 样本范围：{summary['sample_range']}",
        f"- txn 条数：{totals.get('txn_count', 0)}",
        f"- 有 mid1 条数：{totals.get('mid1_txn_count', 0)}",
        f"- mid1 成功率（txn 维度）：{totals.get('mid1_txn_count', 0)}/{totals.get('txn_count', 0)} ({percent(totals.get('mid1_txn_count', 0), totals.get('txn_count', 0))})",
        f"- mid1 item 数：{totals.get('mid1_item_count', 0)}",
        f"- 有 direct success 数（txn 维度）：{totals.get('direct_success_txn', 0)}",
        f"- direct success 数（item 维度）：{totals.get('direct_success_item', 0)}",
        f"- dynamic success 数（item 维度）：{totals.get('dynamic_success_item', 0)}",
        f"- direct 请求总数：{totals.get('direct_req_total', 0)}",
        f"- direct 响应总数：{totals.get('direct_resp_total', 0)}",
        f"- direct revert 总数：{totals.get('direct_revert_total', 0)}",
        "",
        "## 汇总分布",
        "",
        "### revert step 分布（step_idx）",
        "",
        render_counter(d.get("step_idx", {})),
        "",
        "### revert step 分布（step_tag + 语义 + 计数）",
        "",
        render_counter(d.get("step_tag", {})),
        "",
        "### root cause 分布",
        "",
        render_counter(d.get("root_cause", {})),
        "",
        "### root-only 解码结果",
        "",
        render_counter(d.get("root_only", {})),
        "",
        "## 代表性样本（3 条）",
        "",
    ]
    for item in details[:3]:
        lines.extend(
            [
                f"- resp_index={item['resp_index']} id={item['id']} step_idx={item['step_idx']} step_tag={item['step_tag']}",
                f"  trace_error_path={item['trace_error_path']} root_cause={item['root_cause']}",
            ]
        )
    lines.extend(["", "## 逐条明细", ""])
    for item in details:
        lines.extend(
            [
                f"### resp_index={item['resp_index']} id={item['id']}",
                "",
                f"- txHash: {item['txHash']}",
                f"- revert所在step: {item['step_idx']} {item['step_tag']} {item['step_name']} | {item['semantic']}",
                f"- root_cause: {item['root_cause']}",
                f"- trace_error_path: {item['trace_error_path']}",
                f"- reqs文件: {item['reqs_file']}",
                f"- resps文件: {item['resps_file']}",
                f"- mid1文件: {item['mid1_file']}",
                f"- DuralPathIdx: {item['DuralPathIdx']}",
                f"- decode_mismatch: {item['decode_mismatch'] or '无'}",
                "",
                "```text",
                item["calldata"],
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="batch dir or *_direct_resps.json files")
    parser.add_argument("-o", "--output", type=Path, help="report path, default: <batch>/direct_fail_report.md")
    parser.add_argument("--no-report", action="store_true", help="print summary only; do not write markdown")
    parser.add_argument("--json", action="store_true", help="print full JSON summary")
    args = parser.parse_args(argv)

    batch_dir, resps = find_batch_inputs(args.inputs)
    summary = analyze(batch_dir, resps, not args.no_report, args.output)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        totals = summary["totals"]
        print(f"sample_range={summary['sample_range']}")
        print(f"direct_resps_files={summary['files_seen']}")
        print(f"direct_resp_total={totals.get('direct_resp_total', 0)}")
        print(f"direct_revert_total={totals.get('direct_revert_total', 0)}")
        print(f"direct_success_item={totals.get('direct_success_item', 0)}")
        if "report_path" in summary:
            print(f"report={summary['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
