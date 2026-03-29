/**
 * アップロード画像のクライアントサイド EXIF メタデータ除去。
 *
 * Canvas API 経由で JPEG/PNG 画像を再エンコードし、
 * すべての EXIF メタデータ（GPS座標、カメラ情報など）を自然に除去する。
 *
 * モダンブラウザ（iOS Safari 13.1+、Chrome 81+、Firefox 26+）は
 * <img> 要素への画像読み込み時に EXIF Orientation を自動適用するため、
 * 手動での向き処理は不要 — Canvas 経由の再エンコードのみで対応。
 *
 * GIF と WebP ファイルはアニメーションの可能性があるためそのまま返す。
 */

/**
 * File を HTMLImageElement として読み込む。
 * ブラウザが読み込み時に EXIF orientation を自動適用する。
 */
function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);

    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Failed to load image"));
    };
    img.src = url;
  });
}

/**
 * Canvas API 経由で画像ファイルを再エンコードし EXIF メタデータを除去する。
 *
 * ブラウザが画像読み込み時に EXIF orientation を自動適用するため、
 * Canvas に描画すると EXIF データ（GPS、カメラ情報、向きタグを含む）なしの
 * 正しい向きの画像が生成される。
 *
 * 同じ名前と MIME タイプだが EXIF データなしの新しい File を返す。
 *
 * GIF と WebP ファイルはそのまま返す（アニメーションの可能性があるため）。
 */
export async function stripExifFromFile(file: File): Promise<File> {
  const type = file.type.toLowerCase();

  // GIF と WebP をスキップ — アニメーションの可能性があり Canvas ではフラット化される
  if (type === "image/gif" || type === "image/webp") {
    return file;
  }

  // JPEG と PNG のみ処理
  if (type !== "image/jpeg" && type !== "image/png") {
    return file;
  }

  // 画像を読み込み — ブラウザが EXIF orientation を自動適用
  const img = await loadImage(file);

  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return file;
  }

  // 既に向き補正済みの画像を描画 — Canvas 出力には EXIF メタデータなし
  ctx.drawImage(img, 0, 0);

  // Canvas を適切なフォーマットで Blob に変換
  const outputType = type === "image/png" ? "image/png" : "image/jpeg";
  const quality = type === "image/jpeg" ? 0.92 : undefined;

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => {
        if (b) resolve(b);
        else reject(new Error("Canvas toBlob failed"));
      },
      outputType,
      quality,
    );
  });

  return new File([blob], file.name, { type: outputType });
}

/**
 * ファイル配列を処理し、対応する画像タイプから EXIF メタデータを除去する。
 * 非画像ファイルと非対応フォーマットはそのまま返す。
 */
export async function stripExifFromFiles(files: File[]): Promise<File[]> {
  return Promise.all(files.map(stripExifFromFile));
}
