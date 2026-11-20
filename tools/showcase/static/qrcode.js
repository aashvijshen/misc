/**
 * Pure-JS Local QR Code Generator (ISO/IEC 18004, Byte Mode, EC Level M, Versions 1-10)
 * Zero network calls — keeps UPI IDs and payment links 100% private on device.
 */
(function (global) {
  "use strict";

  // Total codewords & EC codewords per block for EC Level M, Versions 1..10:
  // [totalDataBytes, ecBytesPerBlock, numBlocksGroup1, dataPerBlockG1, numBlocksGroup2, dataPerBlockG2]
  const VERSION_TABLE_M = [
    null,
    [16, 10, 1, 16, 0, 0],   // V1  (21x21)
    [28, 16, 1, 28, 0, 0],   // V2  (25x25)
    [44, 26, 1, 44, 0, 0],   // V3  (29x29)
    [64, 18, 2, 32, 0, 0],   // V4  (33x33)
    [86, 24, 2, 43, 0, 0],   // V5  (37x37)
    [108, 16, 4, 27, 0, 0],  // V6  (41x41)
    [124, 18, 4, 31, 0, 0],  // V7  (45x45)
    [154, 22, 2, 38, 2, 39], // V8  (49x49)
    [182, 22, 3, 36, 2, 37], // V9  (53x53)
    [216, 26, 4, 43, 1, 44], // V10 (57x57)
  ];

  const ALIGNMENT_POS = [
    null,
    [],
    [6, 18],
    [6, 22],
    [6, 26],
    [6, 30],
    [6, 34],
    [6, 22, 38],
    [6, 24, 42],
    [6, 26, 46],
    [6, 28, 50],
  ];

  // GF(256) log/exp tables (primitive polynomial x^8 + x^4 + x^3 + x^2 + 1 = 0x11d)
  const GF_EXP = new Uint8Array(512);
  const GF_LOG = new Uint8Array(256);
  (function initGF() {
    let x = 1;
    for (let i = 0; i < 255; i++) {
      GF_EXP[i] = x;
      GF_LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11d;
    }
    for (let i = 255; i < 512; i++) {
      GF_EXP[i] = GF_EXP[i - 255];
    }
  })();

  function gfMul(a, b) {
    if (a === 0 || b === 0) return 0;
    return GF_EXP[GF_LOG[a] + GF_LOG[b]];
  }

  function rsGeneratorPoly(degree) {
    let poly = new Uint8Array([1]);
    for (let i = 0; i < degree; i++) {
      const next = new Uint8Array(poly.length + 1);
      const root = GF_EXP[i];
      for (let j = 0; j < poly.length; j++) {
        next[j] ^= poly[j];
        next[j + 1] ^= gfMul(poly[j], root);
      }
      poly = next;
    }
    return poly;
  }

  function rsComputeRemainder(data, ecLen) {
    const gen = rsGeneratorPoly(ecLen);
    const rem = new Uint8Array(ecLen);
    for (let i = 0; i < data.length; i++) {
      const factor = data[i] ^ rem[0];
      for (let j = 0; j < ecLen - 1; j++) {
        rem[j] = rem[j + 1] ^ gfMul(gen[j + 1], factor);
      }
      rem[ecLen - 1] = gfMul(gen[ecLen], factor);
    }
    return rem;
  }

  function encodeMatrix(text) {
    const bytes = new TextEncoder().encode(text);
    let version = 0;
    for (let v = 1; v <= 10; v++) {
      const charCountBits = v <= 9 ? 8 : 16;
      const maxBytes = Math.floor((VERSION_TABLE_M[v][0] * 8 - 4 - charCountBits) / 8);
      if (bytes.length <= maxBytes) {
        version = v;
        break;
      }
    }
    if (!version) {
      throw new Error("QR payload exceeds Version 10 capacity (" + bytes.length + " bytes)");
    }

    const [totalDataBytes, ecPerBlock, g1Blocks, g1Len, g2Blocks, g2Len] = VERSION_TABLE_M[version];
    const bits = [];
    const pushBits = (val, len) => {
      for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1);
    };

    // Mode indicator: Byte mode = 0100
    pushBits(0b0100, 4);
    pushBits(bytes.length, version <= 9 ? 8 : 16);
    for (let i = 0; i < bytes.length; i++) pushBits(bytes[i], 8);

    // Terminator up to 4 zero bits
    const capacityBits = totalDataBytes * 8;
    const term = Math.min(4, capacityBits - bits.length);
    for (let i = 0; i < term; i++) bits.push(0);
    while (bits.length % 8 !== 0) bits.push(0);

    const dataCodewords = new Uint8Array(totalDataBytes);
    let byteIdx = 0;
    for (let i = 0; i < bits.length; i += 8) {
      let b = 0;
      for (let k = 0; k < 8; k++) b = (b << 1) | bits[i + k];
      dataCodewords[byteIdx++] = b;
    }
    const padBytes = [0xec, 0x11];
    let p = 0;
    while (byteIdx < totalDataBytes) {
      dataCodewords[byteIdx++] = padBytes[p++ & 1];
    }

    // Split into blocks & compute RS EC
    const dataBlocks = [];
    const ecBlocks = [];
    let offset = 0;
    for (let b = 0; b < g1Blocks; b++) {
      const blk = dataCodewords.slice(offset, offset + g1Len);
      offset += g1Len;
      dataBlocks.push(blk);
      ecBlocks.push(rsComputeRemainder(blk, ecPerBlock));
    }
    for (let b = 0; b < g2Blocks; b++) {
      const blk = dataCodewords.slice(offset, offset + g2Len);
      offset += g2Len;
      dataBlocks.push(blk);
      ecBlocks.push(rsComputeRemainder(blk, ecPerBlock));
    }

    // Interleave data codewords, then EC codewords
    const finalBytes = [];
    const maxDataLen = Math.max(g1Len, g2Len);
    for (let i = 0; i < maxDataLen; i++) {
      for (let b = 0; b < dataBlocks.length; b++) {
        if (i < dataBlocks[b].length) finalBytes.push(dataBlocks[b][i]);
      }
    }
    for (let i = 0; i < ecPerBlock; i++) {
      for (let b = 0; b < ecBlocks.length; b++) {
        finalBytes.push(ecBlocks[b][i]);
      }
    }

    const size = version * 4 + 17;
    const modules = Array.from({ length: size }, () => new Uint8Array(size));
    const isFunc = Array.from({ length: size }, () => new Uint8Array(size));

    function setFunctionModule(x, y, dark) {
      if (x < 0 || y < 0 || x >= size || y >= size) return;
      modules[y][x] = dark ? 1 : 0;
      isFunc[y][x] = 1;
    }

    function drawFinder(cx, cy) {
      for (let dy = -4; dy <= 4; dy++) {
        for (let dx = -4; dx <= 4; dx++) {
          const dist = Math.max(Math.abs(dx), Math.abs(dy));
          setFunctionModule(cx + dx, cy + dy, dist !== 2 && dist !== 4);
        }
      }
    }

    drawFinder(3, 3);
    drawFinder(size - 4, 3);
    drawFinder(3, size - 4);

    // Timing patterns
    for (let i = 0; i < size; i++) {
      if (!isFunc[6][i]) setFunctionModule(i, 6, i % 2 === 0);
      if (!isFunc[i][6]) setFunctionModule(6, i, i % 2 === 0);
    }

    // Alignment patterns
    const align = ALIGNMENT_POS[version];
    for (let i = 0; i < align.length; i++) {
      for (let j = 0; j < align.length; j++) {
        if (
          (i === 0 && j === 0) ||
          (i === 0 && j === align.length - 1) ||
          (i === align.length - 1 && j === 0)
        ) {
          continue;
        }
        const cx = align[i];
        const cy = align[j];
        for (let dy = -2; dy <= 2; dy++) {
          for (let dx = -2; dx <= 2; dx++) {
            setFunctionModule(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
          }
        }
      }
    }

    // Reserve format info & dark module
    for (let i = 0; i <= 8; i++) {
      if (i !== 6) {
        setFunctionModule(8, i, false);
        setFunctionModule(i, 8, false);
      }
    }
    for (let i = 0; i < 8; i++) {
      setFunctionModule(size - 1 - i, 8, false);
      setFunctionModule(8, size - 1 - i, false);
    }
    setFunctionModule(8, size - 8, true); // Dark module

    // Version info for >= 7
    if (version >= 7) {
      let rem = version;
      for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
      const verBits = (version << 12) | rem;
      for (let i = 0; i < 18; i++) {
        const bit = ((verBits >>> i) & 1) !== 0;
        const a = size - 11 + (i % 3);
        const b = Math.floor(i / 3);
        setFunctionModule(a, b, bit);
        setFunctionModule(b, a, bit);
      }
    }

    // Place data bits in upward/downward 2-column zig-zag
    let bitIdx = 0;
    const totalBits = finalBytes.length * 8;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < size; vert++) {
        for (let j = 0; j < 2; j++) {
          const x = right - j;
          const upward = ((right + 1) & 2) === 0;
          const y = upward ? size - 1 - vert : vert;
          if (!isFunc[y][x] && bitIdx < totalBits) {
            const dark = ((finalBytes[bitIdx >>> 3] >>> (7 - (bitIdx & 7))) & 1) !== 0;
            modules[y][x] = dark ? 1 : 0;
            bitIdx++;
          }
        }
      }
    }

    function drawFormatBits(mat, mask) {
      // EC Level M indicator = 00
      const data = (0b00 << 3) | mask;
      let rem = data;
      for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
      const bits15 = ((data << 10) | rem) ^ 0x5412;

      const bit = (i) => ((bits15 >>> i) & 1);
      // Around top-left
      for (let i = 0; i <= 5; i++) mat[i][8] = bit(i);
      mat[7][8] = bit(6);
      mat[8][8] = bit(7);
      mat[8][7] = bit(8);
      for (let i = 9; i < 15; i++) mat[8][14 - i] = bit(i);

      // Top-right & bottom-left
      for (let i = 0; i < 8; i++) mat[8][size - 1 - i] = bit(i);
      for (let i = 8; i < 15; i++) mat[size - 15 + i][8] = bit(i);
      mat[size - 8][8] = 1;
    }

    const maskFns = [
      (x, y) => (x + y) % 2 === 0,
      (x, y) => y % 2 === 0,
      (x, y) => x % 3 === 0,
      (x, y) => (x + y) % 3 === 0,
      (x, y) => (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0,
      (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
      (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
      (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
    ];

    function penaltyScore(mat) {
      let score = 0;
      for (let y = 0; y < size; y++) {
        let runColor = mat[y][0];
        let runLen = 1;
        for (let x = 1; x < size; x++) {
          if (mat[y][x] === runColor) {
            runLen++;
            if (runLen === 5) score += 3;
            else if (runLen > 5) score += 1;
          } else {
            runColor = mat[y][x];
            runLen = 1;
          }
        }
      }
      for (let x = 0; x < size; x++) {
        let runColor = mat[0][x];
        let runLen = 1;
        for (let y = 1; y < size; y++) {
          if (mat[y][x] === runColor) {
            runLen++;
            if (runLen === 5) score += 3;
            else if (runLen > 5) score += 1;
          } else {
            runColor = mat[y][x];
            runLen = 1;
          }
        }
      }
      for (let y = 0; y < size - 1; y++) {
        for (let x = 0; x < size - 1; x++) {
          const c = mat[y][x];
          if (c === mat[y][x + 1] && c === mat[y + 1][x] && c === mat[y + 1][x + 1]) {
            score += 3;
          }
        }
      }
      return score;
    }

    let bestMatrix = null;
    let bestPenalty = Infinity;
    for (let m = 0; m < 8; m++) {
      const candidate = modules.map((row) => new Uint8Array(row));
      const fn = maskFns[m];
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          if (!isFunc[y][x] && fn(x, y)) candidate[y][x] ^= 1;
        }
      }
      drawFormatBits(candidate, m);
      const pen = penaltyScore(candidate);
      if (pen < bestPenalty) {
        bestPenalty = pen;
        bestMatrix = candidate;
      }
    }

    return bestMatrix;
  }

  function toSVG(text, opts) {
    const options = Object.assign({ margin: 3, dark: "#1B1917", light: "#FFFFFF" }, opts || {});
    const mat = encodeMatrix(text);
    const n = mat.length;
    const total = n + options.margin * 2;
    let path = "";
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        if (mat[y][x]) {
          path += `M${x + options.margin},${y + options.margin}h1v1h-1z`;
        }
      }
    }
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${total} ${total}" shape-rendering="crispEdges" role="img" aria-label="UPI Payment QR Code"><rect width="${total}" height="${total}" fill="${options.light}" rx="1.5"/><path d="${path}" fill="${options.dark}"/></svg>`;
  }

  function drawOnCanvas(ctx, text, x0, y0, boxPx, opts) {
    const options = Object.assign({ margin: 2, dark: "#1B1917", light: "#FFFFFF" }, opts || {});
    const mat = encodeMatrix(text);
    const n = mat.length;
    const total = n + options.margin * 2;
    const cell = boxPx / total;
    ctx.fillStyle = options.light;
    ctx.fillRect(x0, y0, boxPx, boxPx);
    ctx.fillStyle = options.dark;
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        if (mat[y][x]) {
          ctx.fillRect(
            Math.round(x0 + (x + options.margin) * cell),
            Math.round(y0 + (y + options.margin) * cell),
            Math.ceil(cell),
            Math.ceil(cell)
          );
        }
      }
    }
  }

  global.LocalQR = { encodeMatrix, toSVG, drawOnCanvas };
})(typeof window !== "undefined" ? window : globalThis);
