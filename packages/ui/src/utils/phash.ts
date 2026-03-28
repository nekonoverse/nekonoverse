/**
 * Canvas API 経由の絵文字画像の知覚ハッシュ（pHash）計算。
 *
 * アルゴリズム:
 * 1. 画像を読み込み → 32x32 Canvas に描画 → グレースケールピクセルを抽出
 * 2. 32x32 行列に 2D DCT を計算
 * 3. 左上 8x8 の DCT 係数を取得（DC成分を除く）
 * 4. 中央値で閾値処理 → 64ビットハッシュを16進文字列として出力
 */

const HASH_SIZE = 8;
const SAMPLE_SIZE = 32;

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load image"));
    img.src = url;
  });
}

function getGrayscalePixels(img: HTMLImageElement): Float64Array | null {
  const canvas = document.createElement("canvas");
  canvas.width = SAMPLE_SIZE;
  canvas.height = SAMPLE_SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  ctx.drawImage(img, 0, 0, SAMPLE_SIZE, SAMPLE_SIZE);
  const imageData = ctx.getImageData(0, 0, SAMPLE_SIZE, SAMPLE_SIZE);
  const pixels = new Float64Array(SAMPLE_SIZE * SAMPLE_SIZE);

  for (let i = 0; i < pixels.length; i++) {
    const offset = i * 4;
    // ITU-R BT.601 輝度
    pixels[i] =
      0.299 * imageData.data[offset] +
      0.587 * imageData.data[offset + 1] +
      0.114 * imageData.data[offset + 2];
  }
  return pixels;
}

function dct1d(input: Float64Array, output: Float64Array, N: number): void {
  for (let k = 0; k < N; k++) {
    let sum = 0;
    for (let n = 0; n < N; n++) {
      sum += input[n] * Math.cos((Math.PI / N) * (n + 0.5) * k);
    }
    output[k] = sum;
  }
}

function dct2d(pixels: Float64Array): Float64Array {
  const N = SAMPLE_SIZE;
  const result = new Float64Array(N * N);
  const temp = new Float64Array(N);
  const row = new Float64Array(N);

  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) row[x] = pixels[y * N + x];
    dct1d(row, temp, N);
    for (let x = 0; x < N; x++) result[y * N + x] = temp[x];
  }

  const col = new Float64Array(N);
  for (let x = 0; x < N; x++) {
    for (let y = 0; y < N; y++) col[y] = result[y * N + x];
    dct1d(col, temp, N);
    for (let y = 0; y < N; y++) result[y * N + x] = temp[y];
  }

  return result;
}

export async function computePhash(url: string): Promise<string | null> {
  try {
    const img = await loadImage(url);
    const pixels = getGrayscalePixels(img);
    if (!pixels) return null;

    const dctResult = dct2d(pixels);

    const coefficients: number[] = [];
    for (let y = 0; y < HASH_SIZE; y++) {
      for (let x = 0; x < HASH_SIZE; x++) {
        if (y === 0 && x === 0) continue;
        coefficients.push(dctResult[y * SAMPLE_SIZE + x]);
      }
    }

    const sorted = [...coefficients].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    const median =
      sorted.length % 2 === 0
        ? (sorted[mid - 1] + sorted[mid]) / 2
        : sorted[mid];

    let hash = 0n;
    let bitIndex = 0;
    for (let y = 0; y < HASH_SIZE; y++) {
      for (let x = 0; x < HASH_SIZE; x++) {
        if (y === 0 && x === 0) {
          bitIndex++;
          continue;
        }
        if (dctResult[y * SAMPLE_SIZE + x] > median) {
          hash |= 1n << BigInt(bitIndex);
        }
        bitIndex++;
      }
    }

    return hash.toString(16).padStart(16, "0");
  } catch {
    return null;
  }
}

export function hammingDistance(a: string, b: string): number {
  const va = BigInt("0x" + a);
  const vb = BigInt("0x" + b);
  let xor = va ^ vb;
  let count = 0;
  while (xor > 0n) {
    count += Number(xor & 1n);
    xor >>= 1n;
  }
  return count;
}

export const PHASH_THRESHOLD = 10;
