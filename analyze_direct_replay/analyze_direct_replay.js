#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const KNOWN_SELECTORS = {
  '0x0ab35bb0': 'duralTradeFromWETH',
  '0x022c0d9f': 'V2Swap',
  '0x095ea7b3': 'approve',
  '0x0b0d9c09': 'V4Take',
  '0x10d1e85c': 'uniswapV2Call',
  '0x11da60b4': 'V4Settle',
  '0x128acb08': 'V3Swap',
  '0x23b872dd': 'erc20_transferFrom',
  '0x36c78516': 'core_or_vault_internal',
  '0x48c89491': 'locked_or_internal',
  '0x5b41b908': 'curveV2_256_Swap',
  '0x65b2489b': 'curveV2_ul_256_Swap',
  '0x68a24fe0': 'core_or_vault_internal',
  '0x70a08231': 'balanceOf',
  '0x750283bc': 'core_or_vault_internal',
  '0x8201aa3f': 'balancerV3_like_internal',
  '0x91dd7346': 'locked_or_internal',
  '0xa5841194': 'V4Sync',
  '0xa9059cbb': 'transfer',
  '0xd0e30db0': 'depositWETH',
  '0xf3cd914c': 'V4Swap',
  '0xf83d08ba': 'core_or_vault_internal',
  '0xfa461e33': 'uniswapV3SwapCallback',
};

const ROUTER_CUSTOM_ERRORS = {
  '0xe39aafee': { name: 'NoProfit', label: 'NoProfit()', category: 'post_check_NoProfit', semantic: 'checkProfitAndShare.NoProfit' },
  '0x7005668f': { name: 'TradeFailed', label: 'TradeFailed(uint256)', category: 'post_check_TradeFailed', semantic: 'RouterProxyV8Direct.TradeFailed' },
  '0xdd85b49d': { name: 'InvalidDexType', label: 'InvalidDexType(uint8)', category: 'post_check_InvalidDexType', semantic: 'RouterProxyV8Direct.InvalidDexType' },
  '0x0453a8bb': { name: 'InvalidExactOutputDex', label: 'InvalidExactOutputDex(uint8)', category: 'post_check_InvalidExactOutputDex', semantic: 'RouterProxyV8Direct.InvalidExactOutputDex' },
  '0x28393780': { name: 'InvalidFlashLoanSender', label: 'InvalidFlashLoanSender(address)', category: 'post_check_InvalidFlashLoanSender', semantic: 'RouterProxyV8Direct.InvalidFlashLoanSender' },
};

const STEP_TAG_META = {
  '030000': 'uniswapV3/smarDex',
  '040000': 'uniswapV3/smarDex',
  '050000': 'curveV2',
  '070100': 'multiV4',
  '070200': 'multiV4Settle',
  '080100': 'multiCore',
  '080200': 'multiCoreSettle',
  '090100': 'multiCoreV3',
  '090200': 'multiCoreV3Settle',
  '0a0100': 'multiBalancerV3',
  '0a0200': 'multiBalancerV3Settle',
  '120000': 'v2-with-args',
  'ff0100': 'transfer',
  'ff0200': 'approve',
  'ff0300': 'permit',
  'ff0600': 'depositWETH',
};

const CURVE_SELECTORS = new Set(['0x3df02124', '0x5b41b908', '0xa6417ed6', '0x65b2489b']);
const CORE_INTERNAL_SELECTORS = new Set(['0xf83d08ba', '0xb45a3c0e', '0x750283bc', '0x68a24fe0', '0x36c78516']);
const MULTI_INTERNAL_SELECTORS = new Set(['0x48c89491', '0x91dd7346', '0xf3cd914c', '0x0b0d9c09', '0xa5841194', '0x11da60b4']);

function main() {
  const args = parseArgs(process.argv.slice(2));
  const resolved = resolveInput(args.input || '.');
  const report = analyzeBatch(resolved, args);
  const markdown = renderMarkdown(report);

  if (args.writeReport) {
    fs.writeFileSync(report.outPath, markdown);
  }
  if (args.jsonOut) {
    fs.writeFileSync(args.jsonOut, JSON.stringify(report, null, 2));
  }

  process.stdout.write(markdown);
}

function parseArgs(argv) {
  const args = {
    input: null,
    writeReport: true,
    jsonOut: '',
    outPath: '',
    single: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--') && !args.input) {
      args.input = token;
      continue;
    }
    if (token === '--single') {
      args.single = true;
      continue;
    }
    if (token === '--stdout-only') {
      args.writeReport = false;
      continue;
    }
    if (token === '--out') {
      args.outPath = argv[index + 1] || '';
      index += 1;
      continue;
    }
    if (token === '--json-out') {
      args.jsonOut = argv[index + 1] || '';
      index += 1;
      continue;
    }
  }
  return args;
}

function resolveInput(inputPath) {
  const absolutePath = path.resolve(inputPath);
  if (!fs.existsSync(absolutePath)) {
    throw new Error(`input not found: ${inputPath}`);
  }

  const stat = fs.statSync(absolutePath);
  if (stat.isDirectory()) {
    const snapshotDir = fs.existsSync(path.join(absolutePath, 'go_replay_snapshots'))
      ? path.join(absolutePath, 'go_replay_snapshots')
      : absolutePath;
    return {
      inputPath: absolutePath,
      batchDir: absolutePath,
      snapshotDir,
      singlePrefix: '',
    };
  }

  if (!absolutePath.endsWith('_direct_resps.json') && !absolutePath.endsWith('_direct_resp.json')) {
    throw new Error(`unsupported input file: ${inputPath}`);
  }

  const snapshotDir = path.dirname(absolutePath);
  const batchDir = path.basename(snapshotDir) === 'go_replay_snapshots' ? path.dirname(snapshotDir) : snapshotDir;
  const singlePrefix = path.basename(absolutePath).replace(/_direct_resps?\.json$/, '');
  return {
    inputPath: absolutePath,
    batchDir,
    snapshotDir,
    singlePrefix,
  };
}

function analyzeBatch(resolved, args) {
  const groups = collectGroups(resolved.snapshotDir, args.single ? resolved.singlePrefix : '');
  let csvRows = loadCsvRows(resolved.batchDir);
  if (args.single && resolved.singlePrefix) {
    const shortHashMatch = resolved.singlePrefix.match(/opportunity\.replay\.([0-9a-f]{8})$/i);
    if (shortHashMatch) {
      const shortHash = shortHashMatch[1].toLowerCase();
      csvRows = csvRows.filter((row) => String(row.txHash || '').toLowerCase().slice(2, 10) === shortHash);
    } else {
      csvRows = [];
    }
  }
  const txHashByShort = buildTxHashMap(csvRows);

  let totalMid1Items = 0;
  let derivedTxnWithMid1 = 0;
  let derivedTxnWithDirectSuccess = 0;
  let directReqCount = 0;
  let directRespCount = 0;
  let directSuccessCount = 0;
  let directRevertCount = 0;
  let directNotExecutedCount = 0;

  const revertDetails = [];
  const rootOnlyMap = new Map();

  for (const group of groups) {
    const reqs = loadOptionalJson(group.reqsPath, []);
    const resps = loadOptionalRespJson(group.respsPath);
    const mid1 = loadOptionalJson(group.mid1Path, []);

    totalMid1Items += mid1.length;
    if (mid1.length > 0) {
      derivedTxnWithMid1 += 1;
    }

    const reqById = new Map(reqs.map((item, index) => [normalizeIndex(item?.id, index), item]));
    const respAnalyses = new Map();
    let groupHasSuccess = false;

    directReqCount += reqs.length;
    directRespCount += resps.length;

    resps.forEach((item, index) => {
      const id = normalizeIndex(item?.id, index);
      const analysis = analyzeResponseItem({
        item,
        index,
        group,
        mid1Item: Array.isArray(mid1) ? mid1[id] : null,
        reqItem: reqById.get(id) || null,
      });
      respAnalyses.set(id, analysis);
      if (analysis.isRevert) {
        directRevertCount += 1;
        revertDetails.push(analysis);
        if (analysis.traceErrorPath === 'root_only' && analysis.rootSelector) {
          rootOnlyMap.set(analysis.rootSelector, (rootOnlyMap.get(analysis.rootSelector) || 0) + 1);
        }
      } else {
        directSuccessCount += 1;
        groupHasSuccess = true;
      }
    });

    if (groupHasSuccess) {
      derivedTxnWithDirectSuccess += 1;
    }

    for (let index = 0; index < mid1.length; index += 1) {
      const hasReq = reqById.has(index);
      const resp = respAnalyses.get(index);
      if (!hasReq && !resp) {
        directNotExecutedCount += 1;
      }
    }

    for (const detail of revertDetails.filter((entry) => entry.groupPrefix === group.prefix)) {
      const shortHash = group.shortTxHash;
      detail.txHash = txHashByShort.get(shortHash) || detail.txHash || shortHash;
    }
  }

  const csvStats = deriveCsvStats(csvRows);
  const txnCount = csvStats.txnCount || groups.length;
  const blockMatchCount = csvStats.blockMatchCount || txnCount;
  const noBlockMatchCount = csvStats.noBlockMatchCount || 0;
  const txnWithMid1 = csvStats.txnWithMid1 || derivedTxnWithMid1;
  const txnWithDirectSuccess = csvStats.txnWithDirectSuccess || derivedTxnWithDirectSuccess;
  const mid1ItemCount = csvStats.mid1ItemCount || totalMid1Items;
  const dynamicSuccessCount = csvStats.dynamicSuccessCount || totalMid1Items;
  const directSuccessItemCount = csvStats.directSuccessItemCount || directSuccessCount;

  const byStepIdx = groupCounts(revertDetails, (entry) => String(entry.stepIdx));
  const byStepTag = groupCounts(revertDetails, (entry) => `${entry.stepTag}|${entry.stepSemantic}`);
  const representatives = pickRepresentativeSamples(revertDetails);
  const batchName = path.basename(resolved.batchDir);
  const outPath = args.outPath
    ? path.resolve(args.outPath)
    : path.join(resolved.batchDir, 'direct_fail_report.md');

  return {
    inputPath: resolved.inputPath,
    batchDir: resolved.batchDir,
    batchName,
    outPath,
    totalGroups: groups.length,
    txnCount,
    txnWithMid1,
    txnWithDirectSuccess,
    mid1ItemCount,
    dynamicSuccessCount,
    directSuccessItemCount,
    directReqCount,
    directRespCount,
    directRevertCount,
    directNotExecutedCount,
    directExecutedSuccessCount: directSuccessCount,
    revertDetails,
    byStepIdx,
    byStepTag,
    rootOnlyMap: Array.from(rootOnlyMap.entries()).map(([selector, count]) => ({
      selector,
      count,
      decoded: ROUTER_CUSTOM_ERRORS[selector]?.label || 'unknown',
    })),
    representatives,
  };
}

function collectGroups(snapshotDir, onlyPrefix) {
  const entries = fs.readdirSync(snapshotDir).sort();
  const groups = new Map();

  for (const filename of entries) {
    const match = filename.match(/^(.*)_(direct_resps?|direct_reqs|mid1_Revenue)\.json$/);
    if (!match) {
      continue;
    }
    const prefix = match[1];
    if (onlyPrefix && prefix !== onlyPrefix) {
      continue;
    }
    if (!groups.has(prefix)) {
      const shortHashMatch = prefix.match(/opportunity\.replay\.([0-9a-f]{8})$/i);
      groups.set(prefix, {
        prefix,
        shortTxHash: shortHashMatch ? shortHashMatch[1].toLowerCase() : '',
        respsPath: '',
        reqsPath: '',
        mid1Path: '',
      });
    }
    const entry = groups.get(prefix);
    const fullPath = path.join(snapshotDir, filename);
    if (filename.endsWith('_direct_resps.json') || filename.endsWith('_direct_resp.json')) {
      entry.respsPath = fullPath;
    } else if (filename.endsWith('_direct_reqs.json')) {
      entry.reqsPath = fullPath;
    } else if (filename.endsWith('_mid1_Revenue.json')) {
      entry.mid1Path = fullPath;
    }
  }

  return Array.from(groups.values())
    .filter((item) => item.respsPath)
    .sort((left, right) => left.prefix.localeCompare(right.prefix));
}

function loadCsvRows(batchDir) {
  const csvFile = fs
    .readdirSync(batchDir)
    .filter((name) => /^replay_result_.*\.csv$/.test(name))
    .sort()
    .pop();

  if (!csvFile) {
    return [];
  }

  const text = fs.readFileSync(path.join(batchDir, csvFile), 'utf8').trim();
  if (!text) {
    return [];
  }

  const [headerLine, ...bodyLines] = text.split(/\r?\n/);
  const headers = headerLine.split(',');
  return bodyLines
    .filter(Boolean)
    .map((line) => {
      const values = line.split(',');
      const row = {};
      headers.forEach((header, index) => {
        row[header] = values[index] || '';
      });
      return row;
    });
}

function buildTxHashMap(csvRows) {
  const mapping = new Map();
  for (const row of csvRows) {
    const txHash = String(row.txHash || '').toLowerCase();
    if (/^0x[0-9a-f]{64}$/.test(txHash)) {
      mapping.set(txHash.slice(2, 10), txHash);
    }
  }
  return mapping;
}

function deriveCsvStats(csvRows) {
  if (!csvRows.length) {
    return {
      txnCount: 0,
      blockMatchCount: 0,
      noBlockMatchCount: 0,
      txnWithMid1: 0,
      txnWithDirectSuccess: 0,
      mid1ItemCount: 0,
      directSuccessItemCount: 0,
      dynamicSuccessCount: 0,
    };
  }
  const countFlag = (row, key) => String(row[key] || '').toUpperCase() === 'Y';
  const eligible = csvRows.filter((row) => String(row.error || '').trim() !== 'no_block_match');
  return {
    txnCount: csvRows.length,
    blockMatchCount: eligible.length,
    noBlockMatchCount: csvRows.length - eligible.length,
    txnWithMid1: eligible.filter((row) => countFlag(row, 'mid1Produced')).length,
    txnWithDirectSuccess: eligible.filter((row) => toNumber(row.directSuccessCount) > 0).length,
    mid1ItemCount: eligible.reduce((sum, row) => sum + toNumber(row.mid1RevenueSuccessCount), 0),
    directSuccessItemCount: eligible.reduce((sum, row) => sum + toNumber(row.directSuccessCount), 0),
    dynamicSuccessCount: eligible.reduce((sum, row) => sum + toNumber(row.dynamicSuccessCount), 0),
  };
}

function analyzeResponseItem({ item, index, group, mid1Item, reqItem }) {
  const result = item?.result || {};
  const decode = decodeOuterCalldata(result.input || '');
  const nestedError = findDeepestNestedError(result.calls || []);
  const hasRootError = Boolean(result.error);
  const rootSelector = decodeCustomErrorSelector(result.output || '');
  const rootCustom = rootSelector ? ROUTER_CUSTOM_ERRORS[rootSelector] || null : null;
  const traceChain = nestedError ? formatSelectorChain(nestedError.chain) : 'root_only';
  const location = locateRevertStep({
    steps: decode.steps,
    nestedError,
    hasRootError,
    rootCustom,
  });

  return {
    groupPrefix: group.prefix,
    txHash: group.shortTxHash ? `0x${group.shortTxHash}` : group.prefix,
    reqsPath: group.reqsPath,
    respsPath: group.respsPath,
    mid1Path: group.mid1Path,
    respIndex: index,
    id: normalizeIndex(item?.id, index),
    duralPathIdx: mid1Item?.DuralPathIdx ?? '',
    mid1Desc: getMid1Desc(mid1Item),
    isRevert: hasRootError,
    resultError: result.error || '',
    traceReason: nestedError?.error || (rootCustom ? rootCustom.label : result.error || ''),
    traceErrorPath: traceChain,
    rootSelector,
    selector: decode.selector,
    selectorLabel: selectorLabel(decode.selector),
    offset: decode.offset,
    bytesLen: decode.bytesLen,
    steps: decode.steps,
    stepIdx: location.stepIdx,
    stepTag: location.stepTag,
    stepSemantic: location.stepSemantic,
    calldataSummary: `selector=${decode.selector}${decode.selector ? `(${selectorLabel(decode.selector)})` : ''}, offset=${decode.offset}, bytes_len=${decode.bytesLen}`,
    reqItem,
    mid1Item,
  };
}

function decodeOuterCalldata(inputHex) {
  const clean = strip0x(inputHex);
  if (!clean || clean.length < 8 + 64 + 64) {
    return {
      selector: '',
      offset: 0,
      bytesLen: 0,
      steps: [],
    };
  }

  const selector = `0x${clean.slice(0, 8).toLowerCase()}`;
  const offset = Number(readWord(clean, 8));
  const bytesLen = Number(readWord(clean, 8 + 64));
  const payloadStartNibble = 8 + offset * 2 + 64;
  const payloadHex = clean.slice(payloadStartNibble, payloadStartNibble + bytesLen * 2);
  const decoded = pickBestPathDecode(payloadHex);

  return {
    selector,
    offset,
    bytesLen,
    steps: decoded.steps,
  };
}

function pickBestPathDecode(pathHex) {
  const candidates = [0, 40];
  let best = { score: -1, steps: [] };
  for (const stepStart of candidates) {
    if (stepStart * 2 > pathHex.length) {
      continue;
    }
    const decoded = decodePathSteps(pathHex, stepStart);
    const score =
      (decoded.complete ? 1000 : 0) +
      decoded.knownCount * 10 -
      decoded.unknownCount * 7 -
      decoded.mismatchCount * 30 -
      stepStart;
    if (score > best.score) {
      best = { ...decoded, score };
    }
  }
  return best;
}

function decodePathSteps(pathHex, startBytes) {
  const totalBytes = Math.floor(pathHex.length / 2);
  let offset = startBytes;
  const steps = [];
  let knownCount = 0;
  let unknownCount = 0;
  let mismatchCount = 0;

  while (offset < totalBytes) {
    const remaining = totalBytes - offset;
    if (remaining === 5) {
      const trailerHex = sliceHex(pathHex, offset, 5);
      steps.push({
        stepIdx: steps.length,
        offset,
        length: 5,
        tag: trailerHex.slice(0, 6).toLowerCase(),
        tagLabel: 'trailer(share+gas)',
        semantic: 'trailer(share+gas)',
        raw: trailerHex,
        fields: {},
      });
      offset += 5;
      break;
    }

    const step = decodeSingleStep(pathHex, offset, totalBytes);
    if (!step) {
      mismatchCount += 1;
      steps.push({
        stepIdx: steps.length,
        offset,
        length: remaining,
        tag: 'decode_mismatch',
        tagLabel: 'decode_mismatch',
        semantic: 'decode_mismatch',
        raw: sliceHex(pathHex, offset, remaining),
        fields: {},
      });
      offset = totalBytes;
      break;
    }

    step.stepIdx = steps.length;
    steps.push(step);
    if (step.known) {
      knownCount += 1;
    } else {
      unknownCount += 1;
    }
    offset += step.length;
  }

  return {
    steps,
    knownCount,
    unknownCount,
    mismatchCount,
    complete: offset === totalBytes,
  };
}

function decodeSingleStep(pathHex, offsetBytes, totalBytes) {
  if (offsetBytes + 3 > totalBytes) {
    return null;
  }

  const tag = sliceHex(pathHex, offsetBytes, 3).toLowerCase();
  const header = tag.slice(0, 2);
  const type = tag.slice(2, 4);
  const subType = tag.slice(4, 6);

  const aliasHeader = header === 'a7' ? '07' : header === 'a8' ? '08' : header === 'aa' ? '0a' : header;

  let length = 0;
  let tagLabel = 'unknown';
  let semantic = 'unknown';
  const fields = {};
  let known = true;

  switch (aliasHeader) {
    case '03':
    case '04':
      length = 83;
      tagLabel = STEP_TAG_META[`${aliasHeader}0000`] || 'uniswapV3/smarDex';
      semantic = tagLabel;
      fields.pool = readAddress(pathHex, offsetBytes + 23);
      fields.recipient = readAddress(pathHex, offsetBytes + 43);
      break;
    case '02':
      if (type === '21') {
        length = 103;
      } else if (type === '22') {
        length = 84;
      } else {
        length = 64;
      }
      tagLabel = 'v2-family';
      semantic = 'v2-family';
      fields.pool = readAddress(pathHex, offsetBytes + 23);
      fields.recipient = readAddress(pathHex, offsetBytes + 43);
      break;
    case '12':
      length = 84;
      tagLabel = 'v2-family';
      semantic = 'v2-with-args';
      fields.pool = readAddress(pathHex, offsetBytes + 23);
      fields.recipient = readAddress(pathHex, offsetBytes + 43);
      break;
    case '05':
      length = 85;
      tagLabel = 'curveV2';
      semantic = 'curveV2';
      fields.pool = readAddress(pathHex, offsetBytes + 25);
      fields.recipient = readAddress(pathHex, offsetBytes + 45);
      break;
    case '06':
      if (type === '00') {
        length = 135;
        tagLabel = 'balancerV2';
        semantic = 'balancerV2';
      } else if (type === '01') {
        length = 103;
        tagLabel = 'BPT';
        semantic = 'BPT';
      } else if (type === '02') {
        length = 123;
        tagLabel = 'balancerV3';
        semantic = 'balancerV3';
      } else {
        length = 103;
        tagLabel = 'balancer-family';
        semantic = 'balancer-family';
      }
      break;
    case '07':
      if (type === '02') {
        length = 43;
        tagLabel = 'multiV4Settle';
        semantic = 'multiV4Settle';
      } else {
        const poolLength = readByte(pathHex, offsetBytes + 23);
        length = 64 + poolLength * 46 + 20;
        tagLabel = 'multiV4';
        semantic = 'multiV4';
      }
      break;
    case '08':
      if (type === '02') {
        length = 43;
        tagLabel = 'multiCoreSettle';
        semantic = 'multiCoreSettle';
      } else {
        const poolLength = readByte(pathHex, offsetBytes + 23);
        length = 64 + poolLength * 52 + 20;
        tagLabel = 'multiCore';
        semantic = 'multiCore';
      }
      break;
    case '09':
      if (type === '02') {
        length = 43;
        tagLabel = 'multiCoreV3Settle';
        semantic = 'multiCoreV3Settle';
      } else {
        const poolLength = readByte(pathHex, offsetBytes + 23);
        length = 64 + poolLength * 52 + 20;
        tagLabel = 'multiCoreV3';
        semantic = 'multiCoreV3';
      }
      break;
    case '0a':
      if (type === '02') {
        length = 43;
        tagLabel = 'multiBalancerV3Settle';
        semantic = 'multiBalancerV3Settle';
      } else {
        const poolLength = readByte(pathHex, offsetBytes + 23);
        length = 64 + poolLength * 60 + 20;
        tagLabel = 'multiBalancerV3';
        semantic = 'multiBalancerV3';
      }
      break;
    case '10':
      length = 363;
      tagLabel = 'oneInchLimitOrder';
      semantic = 'oneInchLimitOrder';
      break;
    case '11':
      length = 776;
      tagLabel = 'uniXLimitOrder';
      semantic = 'uniXLimitOrder';
      break;
    case '50':
      length = type === '02' ? 63 : 43;
      tagLabel = 'wrap-family';
      semantic = 'wrap-family';
      break;
    case '51':
      length = 63;
      tagLabel = 'fwSwap';
      semantic = 'fwSwap';
      break;
    case '52':
      length = 63;
      tagLabel = 'dodoV2';
      semantic = 'dodoV2';
      break;
    case '53':
      length = type === '03' ? 103 : 63;
      tagLabel = 'origin-family';
      semantic = 'origin-family';
      break;
    case '54':
      length = type === '02' ? 83 : 43;
      tagLabel = 'relayV2';
      semantic = 'relayV2';
      break;
    case '55':
      length = 63;
      tagLabel = 'syrupMigrator';
      semantic = 'syrupMigrator';
      break;
    case '56':
      length = type === '02' ? 45 : 65;
      tagLabel = 'ohm-family';
      semantic = 'ohm-family';
      break;
    case '57':
    case '58':
    case '59':
      length = 63;
      tagLabel = 'wrap-family';
      semantic = 'wrap-family';
      break;
    case '63':
      length = 83;
      tagLabel = 'aaveV3';
      semantic = 'aaveV3';
      break;
    case '64':
      length = 144;
      tagLabel = 'bancorV2';
      semantic = 'bancorV2';
      break;
    case '65':
      length = type === '01' ? 156 : 84;
      tagLabel = type === '01' ? 'fluidDexLite' : 'fluid';
      semantic = tagLabel;
      break;
    case '67':
      length = 123;
      tagLabel = 'algebraIntegral';
      semantic = 'algebraIntegral';
      break;
    case 'ff':
      if (type === '01') {
        length = 63;
        tagLabel = 'transfer';
        semantic = 'transferExactOut';
      } else if (type === '02') {
        length = 44;
        tagLabel = 'approve';
        semantic = 'approve';
      } else if (type === '03') {
        length = 44;
        tagLabel = 'permit';
        semantic = 'permit';
      } else if (type === '06') {
        length = 23;
        tagLabel = 'depositWETH';
        semantic = 'depositWETH';
      } else {
        return null;
      }
      break;
    default:
      known = false;
      length = totalBytes - offsetBytes;
      tagLabel = 'unknown';
      semantic = 'unknown';
      break;
  }

  if (offsetBytes + length > totalBytes) {
    return null;
  }

  return {
    offset: offsetBytes,
    length,
    tag,
    tagLabel,
    semantic,
    raw: sliceHex(pathHex, offsetBytes, length),
    fields,
    known,
    normalizedTag: normalizeStepTag(aliasHeader, type, subType),
  };
}

function locateRevertStep({ steps, nestedError, hasRootError, rootCustom }) {
  const nonTrailerSteps = steps.filter((step) => step.semantic !== 'trailer(share+gas)');
  const settleSteps = nonTrailerSteps.filter((step) =>
    ['multiV4Settle', 'multiCoreSettle', 'multiCoreV3Settle', 'multiBalancerV3Settle'].includes(step.semantic));

  if (hasRootError && !nestedError) {
    if (rootCustom) {
      return {
        stepIdx: -1,
        stepTag: rootCustom.category,
        stepSemantic: rootCustom.semantic,
      };
    }
    return {
      stepIdx: -1,
      stepTag: 'root_unknown',
      stepSemantic: 'root_unknown',
    };
  }

  if (!nestedError) {
    const fallback = nonTrailerSteps[nonTrailerSteps.length - 1];
    return fallback
      ? { stepIdx: fallback.stepIdx, stepTag: fallback.tag, stepSemantic: fallback.semantic }
      : { stepIdx: -1, stepTag: 'unknown', stepSemantic: 'unknown' };
  }

  const selectors = nestedError.chain.map((entry) => entry.selector);
  const selectorSet = new Set(selectors);

  const lastSettle = settleSteps[settleSteps.length - 1];
  if ((selectorSet.has('0xfa461e33') || selectorSet.has('0x48c89491') || containsAny(selectorSet, CORE_INTERNAL_SELECTORS)) && lastSettle) {
    return { stepIdx: lastSettle.stepIdx, stepTag: lastSettle.tag, stepSemantic: lastSettle.semantic };
  }

  const scored = nonTrailerSteps
    .map((step) => ({ step, score: scoreStepAgainstTrace(step, nestedError) }))
    .sort((left, right) => right.score - left.score || right.step.stepIdx - left.step.stepIdx);

  if (scored.length && scored[0].score > 0) {
    return {
      stepIdx: scored[0].step.stepIdx,
      stepTag: scored[0].step.tag,
      stepSemantic: scored[0].step.semantic,
    };
  }

  const fallback = nonTrailerSteps[nonTrailerSteps.length - 1];
  return fallback
    ? { stepIdx: fallback.stepIdx, stepTag: fallback.tag, stepSemantic: fallback.semantic }
    : { stepIdx: -1, stepTag: 'unknown', stepSemantic: 'unknown' };
}

function scoreStepAgainstTrace(step, nestedError) {
  let score = 0;
  const traceSelectors = new Set(nestedError.chain.map((entry) => entry.selector));
  const traceAddresses = new Set();
  for (const entry of nestedError.chain) {
    if (entry.from) traceAddresses.add(entry.from.toLowerCase());
    if (entry.to) traceAddresses.add(entry.to.toLowerCase());
  }

  if (step.semantic === 'approve' && traceSelectors.has('0x095ea7b3')) score += 8;
  if (step.semantic === 'transferExactOut' && (traceSelectors.has('0xa9059cbb') || traceSelectors.has('0x23b872dd'))) score += 6;
  if ((step.semantic === 'uniswapV3/smarDex' || step.tag.startsWith('03') || step.tag.startsWith('04')) && (traceSelectors.has('0x128acb08') || traceSelectors.has('0xfa461e33'))) score += 9;
  if (step.semantic === 'curveV2' && containsAny(traceSelectors, CURVE_SELECTORS)) score += 8;
  if (step.semantic === 'multiV4' && containsAny(traceSelectors, MULTI_INTERNAL_SELECTORS)) score += 7;
  if ((step.semantic === 'multiCore' || step.semantic === 'multiCoreV3' || step.semantic === 'multiCoreSettle' || step.semantic === 'multiCoreV3Settle') && containsAny(traceSelectors, CORE_INTERNAL_SELECTORS)) score += 9;
  if (step.semantic === 'multiBalancerV3' && traceSelectors.has('0x8201aa3f')) score += 9;

  for (const value of Object.values(step.fields || {})) {
    if (!value || typeof value !== 'string') {
      continue;
    }
    if (traceAddresses.has(value.toLowerCase())) {
      score += 4;
    }
  }

  return score;
}

function findDeepestNestedError(calls) {
  let best = null;

  function visit(node, chain) {
    if (!node || typeof node !== 'object') {
      return;
    }
    const current = {
      selector: selectorFromInput(node.input || ''),
      from: node.from || '',
      to: node.to || '',
      error: node.error || '',
    };
    const nextChain = chain.concat(current);

    if (node.error) {
      if (!best || nextChain.length > best.chain.length) {
        best = { error: node.error, chain: nextChain };
      }
    }

    if (Array.isArray(node.calls)) {
      for (const child of node.calls) {
        visit(child, nextChain);
      }
    }
  }

  for (const call of calls || []) {
    visit(call, []);
  }

  return best;
}

function formatSelectorChain(chain) {
  if (!chain || !chain.length) {
    return 'root_only';
  }
  return chain
    .map((entry) => `${entry.selector || '0x00000000'}(${selectorLabel(entry.selector)})`)
    .join(' > ');
}

function selectorLabel(selector) {
  return KNOWN_SELECTORS[selector] || 'unknown';
}

function decodeCustomErrorSelector(output) {
  if (typeof output !== 'string') {
    return '';
  }
  const clean = output.trim().toLowerCase();
  if (/^0x[0-9a-f]{8}$/.test(clean)) {
    return clean;
  }
  if (/^0x[0-9a-f]{8}[0-9a-f]+$/.test(clean)) {
    return clean.slice(0, 10);
  }
  return '';
}

function renderMarkdown(report) {
  const lines = [];
  lines.push('# direct_fail_report');
  lines.push('');
  lines.push(`- 样本范围：\`${report.batchName}\``);
  lines.push('');
  lines.push('## 批次级统计');
  lines.push('');
  lines.push(`- txn 条数：\`${report.txnCount}\``);
  lines.push(`- 有 mid1 条数：\`${report.txnWithMid1}\``);
  lines.push(`- mid1 成功率（txn 维度）：\`${pct(report.txnWithMid1, report.txnCount)}\` (\`${report.txnWithMid1}/${report.txnCount}\`)`);
  lines.push(`- mid1 item 数：\`${report.mid1ItemCount}\``);
  lines.push(`- 有 direct success 数（txn 维度）：\`${report.txnWithDirectSuccess}\``);
  lines.push(`- direct success 数（item 维度，directSuccessCount 求和）：\`${report.directSuccessItemCount}\``);
  lines.push(`- dynamic success 数（item 维度，dynamicSuccessCount 求和）：\`${report.dynamicSuccessCount}\``);
  lines.push('');
  lines.push('## direct 请求/响应统计');
  lines.push('');
  lines.push(`- direct 请求总数：\`${report.directReqCount}\``);
  lines.push(`- direct 响应总数：\`${report.directRespCount}\``);
  lines.push(`- direct revert 总数：\`${report.directRevertCount}\``);
  lines.push('');
  lines.push('## 执行状态统计');
  lines.push('');
  lines.push(`- direct 未执行（无 req/无 resp，以 mid1 索引对齐）：\`${report.directNotExecutedCount}\` / \`${report.mid1ItemCount}\` (\`${pct(report.directNotExecutedCount, report.mid1ItemCount)}\`)`);
  lines.push(`- direct 执行成功：\`${report.directExecutedSuccessCount}\` / \`${report.mid1ItemCount}\` (\`${pct(report.directExecutedSuccessCount, report.mid1ItemCount)}\`)`);
  lines.push(`- direct 执行并 reverted：\`${report.directRevertCount}\` / \`${report.mid1ItemCount}\` (\`${pct(report.directRevertCount, report.mid1ItemCount)}\`)`);
  lines.push('');
  lines.push('## 汇总分布');
  lines.push('');
  lines.push(`- revert_total：\`${report.directRevertCount}\``);
  lines.push('');
  lines.push('### revert step 分布（step_idx）');
  lines.push('');
  for (const entry of report.byStepIdx) {
    const label = entry.key === '-1' ? `step_idx \`-1\` (${entry.example?.stepTag || 'root'})` : `step_idx \`${entry.key}\``;
    lines.push(`- ${label}: \`${entry.count}\` (\`${pct(entry.count, report.directRevertCount)}\`)`);
  }
  lines.push('');
  lines.push('### revert step 分布（step_tag + 语义 + 计数）');
  lines.push('');
  for (const entry of report.byStepTag) {
    const [stepTag, semantic] = entry.key.split('|');
    lines.push(`- \`${stepTag}\` (${semantic}): \`${entry.count}\` (\`${pct(entry.count, report.directRevertCount)}\`)`);
  }

  if (report.rootOnlyMap.length) {
    lines.push('');
    lines.push('### root-only 解码');
    lines.push('');
    const totalRootOnly = report.rootOnlyMap.reduce((sum, item) => sum + item.count, 0);
    lines.push(`- \`trace_error_path = root_only\` 共 \`${totalRootOnly}\` 条。`);
    for (const item of report.rootOnlyMap) {
      lines.push(`- \`${item.selector}\` (${item.decoded}): \`${item.count}\``);
    }
    lines.push('- 根因位置：`RouterProxyV8Direct.checkProfitAndShare` 或 Router 顶层 post-check。');
  }

  lines.push('');
  lines.push('## 代表性样本（3 条）');
  lines.push('');
  for (const sample of report.representatives) {
    lines.push(`- txHash前8位 \`${shortTxHash(sample.txHash, 8)}\`, resp_index \`${sample.respIndex}\`, id \`${sample.id}\`, step_idx \`${sample.stepIdx}\`, step_tag \`${sample.stepTag}\`, selector \`${sample.selector}${sample.selector ? `(${sample.selectorLabel})` : ''}\`, trace_error_path \`${sample.traceErrorPath}\``);
  }

  lines.push('');
  lines.push('## 逐条明细');
  lines.push('');
  for (const detail of report.revertDetails) {
    lines.push(`- txHash: \`${detail.txHash}\``);
    lines.push(`  - txHash前8位: \`${shortTxHash(detail.txHash, 8)}\``);
    lines.push(`  - revert所在step: \`idx=${detail.stepIdx}, tag=${detail.stepTag}, semantic=${detail.stepSemantic}\``);
    lines.push(`  - reqs文件: \`${toTestOutputRelative(detail.reqsPath)}\``);
    lines.push(`  - resps文件: \`${toTestOutputRelative(detail.respsPath)}\``);
    lines.push(`  - id: \`${detail.id}\``);
    lines.push(`  - mid1文件: \`${toTestOutputRelative(detail.mid1Path)}\``);
    lines.push(`  - DuralPathIdx: \`${detail.duralPathIdx}\``);
    if (detail.mid1Desc) {
      lines.push(`  - desc: \`${escapeInlineCode(detail.mid1Desc)}\``);
    }
    lines.push(`  - trace_error_path: \`${detail.traceErrorPath}\``);
    if (detail.traceReason) {
      lines.push(`  - trace_reason: \`${detail.traceReason}\``);
    }
    lines.push(`  - calldata拆解: \`${detail.calldataSummary}\``);
    lines.push(`  - steps: \`${renderSteps(detail.steps)}\``);
  }

  lines.push('');
  return `${lines.join('\n')}\n`;
}

function shortTxHash(txHash, hexLen) {
  if (typeof txHash !== 'string') {
    return '';
  }
  const clean = strip0x(txHash).toLowerCase();
  if (!clean) {
    return '';
  }
  return `0x${clean.slice(0, hexLen)}`;
}

function renderSteps(steps) {
  return steps
    .map((step) => `[${step.stepIdx}] ${step.tag}(${step.tagLabel}) len=${step.length}`)
    .join(' | ');
}

function getMid1Desc(mid1Item) {
  const candidates = [
    mid1Item?.BackrunCallData?.Desc,
    mid1Item?.TradeCallParam?.Desc,
    mid1Item?.Desc,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) {
      return candidate.trim();
    }
  }
  return '';
}

function escapeInlineCode(text) {
  return String(text).replace(/`/g, '\\`');
}

function pickRepresentativeSamples(revertDetails) {
  const picked = [];
  const usedTags = new Set();
  for (const detail of revertDetails.sort((left, right) => left.stepIdx - right.stepIdx || left.id - right.id)) {
    if (!usedTags.has(detail.stepTag)) {
      picked.push(detail);
      usedTags.add(detail.stepTag);
    }
    if (picked.length === 3) {
      break;
    }
  }
  return picked;
}

function groupCounts(items, keyFn) {
  const counts = new Map();
  for (const item of items) {
    const key = keyFn(item);
    if (!counts.has(key)) {
      counts.set(key, { key, count: 0, example: item });
    }
    counts.get(key).count += 1;
  }
  return Array.from(counts.values()).sort((left, right) => right.count - left.count || left.key.localeCompare(right.key));
}

function toTestOutputRelative(filePath) {
  if (!filePath) {
    return '';
  }
  const normalized = filePath.split(path.sep).join('/');
  const marker = '/test_output/';
  const idx = normalized.indexOf(marker);
  if (idx >= 0) {
    return normalized.slice(idx + marker.length);
  }
  return normalized;
}

function loadOptionalJson(filePath, fallback) {
  if (!filePath || !fs.existsSync(filePath)) {
    return fallback;
  }
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function loadOptionalRespJson(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return [];
  }
  const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  // Single JSON-RPC response object -> wrap in array
  if (!Array.isArray(parsed)) {
    return [parsed];
  }
  return parsed;
}

function normalizeIndex(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function toNumber(value) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function pct(part, total) {
  if (!total) {
    return '0.00%';
  }
  return `${((part / total) * 100).toFixed(2)}%`;
}

function strip0x(value) {
  return String(value || '').replace(/^0x/i, '').toLowerCase();
}

function sliceHex(hex, startBytes, lengthBytes) {
  return hex.slice(startBytes * 2, (startBytes + lengthBytes) * 2);
}

function readWord(cleanHex, startNibble) {
  const word = cleanHex.slice(startNibble, startNibble + 64) || '0';
  return BigInt(`0x${word || '0'}`);
}

function readByte(hex, offsetBytes) {
  const byte = sliceHex(hex, offsetBytes, 1);
  return Number.parseInt(byte || '00', 16);
}

function readAddress(hex, offsetBytes) {
  const raw = sliceHex(hex, offsetBytes, 20);
  if (!raw || raw.length !== 40) {
    return '';
  }
  return `0x${raw.toLowerCase()}`;
}

function selectorFromInput(input) {
  const clean = strip0x(input);
  return clean.length >= 8 ? `0x${clean.slice(0, 8)}` : '';
}

function normalizeStepTag(header, type, subType) {
  return `${header}${type}${subType}`.toLowerCase();
}

function containsAny(container, items) {
  for (const item of items) {
    if (container.has(item)) {
      return true;
    }
  }
  return false;
}

main();
