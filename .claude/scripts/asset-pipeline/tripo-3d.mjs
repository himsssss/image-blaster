#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import path from "node:path";
import {
  downloadRemoteFiles,
  ensureDir,
  inferMime,
  isDataUri,
  isUrl,
  one,
  parseArgs,
  pathExists,
  readJson,
  requireEnv,
  sanitizeForMetadata,
  writeJson
} from "./fal-queue.mjs";
import { buildRequestSummary, requestPath } from "./request-metadata.mjs";

export const TRIPO_API_BASE = "https://openapi.tripo3d.ai/v3";
export const TRIPO_3D_ENDPOINT = "tripo/v3/generation/image-to-model";
export const TRIPO_3D_PROVIDER = "tripo";
export const DEFAULT_TRIPO_MODEL = "v3.1-20260211";
export const DEFAULT_TRIPO_FACE_LIMIT = 50000;
export const DEFAULT_TRIPO_TEXTURE = true;
export const DEFAULT_TRIPO_ENABLE_PBR = true;
export const DEFAULT_TRIPO_TEXTURE_QUALITY = "standard";
export const DEFAULT_TRIPO_GEOMETRY_QUALITY = "standard";

const TEXTURE_QUALITIES = new Set(["fast", "standard", "detailed", "extreme"]);
const GEOMETRY_QUALITIES = new Set(["standard", "detailed"]);
const FAILED_STATUSES = new Set(["failed", "cancelled", "banned", "expired", "unknown"]);
// Preferred model output first so it becomes the primary model artifact.
const OUTPUT_KEY_ORDER = ["pbr_model_url", "model_url", "base_model_url"];

function normalizeBoolean(value, fieldName) {
  if (typeof value === "boolean") return value;
  const normalized = String(value).trim().toLowerCase();
  if (["true", "1", "yes", "on"].includes(normalized)) return true;
  if (["false", "0", "no", "off"].includes(normalized)) return false;
  throw new Error(`${fieldName} must be true or false.`);
}

function normalizePositiveInteger(value, fieldName) {
  const number = Number(value);
  if (!Number.isInteger(number) || number <= 0) {
    throw new Error(`${fieldName} must be a positive integer.`);
  }
  return number;
}

function normalizeChoice(value, choices, fieldName) {
  const normalized = String(value).trim().toLowerCase();
  if (!choices.has(normalized)) {
    throw new Error(`${fieldName} must be one of: ${[...choices].join(", ")}.`);
  }
  return normalized;
}

export function buildTripo3DInput(options = {}) {
  const model = options.tripoModel || DEFAULT_TRIPO_MODEL;
  const input = {
    model,
    texture: normalizeBoolean(options.texture ?? DEFAULT_TRIPO_TEXTURE, "texture"),
    pbr: normalizeBoolean(options.enablePbr ?? DEFAULT_TRIPO_ENABLE_PBR, "enable-pbr")
  };

  const faceLimit = options.faceLimit ?? DEFAULT_TRIPO_FACE_LIMIT;
  if (faceLimit !== "auto") input.face_limit = normalizePositiveInteger(faceLimit, "face-limit");

  // These options are only accepted by model versions >= v3.0.
  if (!model.startsWith("v2")) {
    input.texture_quality = normalizeChoice(
      options.textureQuality ?? DEFAULT_TRIPO_TEXTURE_QUALITY,
      TEXTURE_QUALITIES,
      "texture-quality"
    );
    input.geometry_quality = normalizeChoice(
      options.geometryQuality ?? DEFAULT_TRIPO_GEOMETRY_QUALITY,
      GEOMETRY_QUALITIES,
      "geometry-quality"
    );
    if (options.smartLowPoly !== undefined) {
      input.smart_low_poly = normalizeBoolean(options.smartLowPoly, "smart-low-poly");
    }
    if (options.quad !== undefined) input.quad = normalizeBoolean(options.quad, "quad");
  }

  if (input.texture_quality === "fast") input.texture_version = "v3.5-20260815";
  if (options.orientation) input.orientation = options.orientation;
  if (options.enableImageAutofix !== undefined) {
    input.enable_image_autofix = normalizeBoolean(options.enableImageAutofix, "enable-image-autofix");
  }

  return input;
}

async function tripoRequest(method, urlPath, { body, form } = {}) {
  const apiKey = await requireEnv("TRIPO_API_KEY");
  const headers = { Authorization: `Bearer ${apiKey}` };
  if (body) headers["Content-Type"] = "application/json";

  const response = await fetch(`${TRIPO_API_BASE}${urlPath}`, {
    method,
    headers,
    body: form || (body ? JSON.stringify(body) : undefined)
  });
  const payload = await response.json().catch(() => ({}));

  if (!response.ok || (payload.code !== undefined && payload.code !== 0)) {
    const detail = payload.message || payload.error_message || payload.suggestion || "";
    throw new Error(
      `Tripo ${method} ${urlPath} failed (${response.status}${payload.code ? `, code ${payload.code}` : ""})${detail ? `: ${detail}` : ""}.`
    );
  }

  return payload.data;
}

async function imageToBlob(image) {
  if (isDataUri(image)) {
    const match = image.match(/^data:([^;,]+)?(;base64)?,(.*)$/);
    if (!match) throw new Error("Invalid data URI");
    const buffer = match[2] ? Buffer.from(match[3], "base64") : Buffer.from(decodeURIComponent(match[3]));
    const mime = match[1] || "image/png";
    return { blob: new Blob([buffer], { type: mime }), fileName: `input.${mime.split("/")[1] || "png"}` };
  }

  if (!(await pathExists(image))) throw new Error(`Input file does not exist: ${image}`);
  const buffer = await readFile(image);
  return { blob: new Blob([buffer], { type: inferMime(image) }), fileName: path.basename(image) };
}

export async function uploadTripoImage(image) {
  if (isUrl(image)) return image;
  const { blob, fileName } = await imageToBlob(image);
  const form = new FormData();
  form.append("file", blob, fileName);
  const data = await tripoRequest("POST", "/files", { form });
  if (!data?.file_token) throw new Error("Tripo upload response did not include file_token.");
  return data.file_token;
}

async function patchMetadata(metadataPath, patch) {
  if (!metadataPath) return;
  const previous = (await pathExists(metadataPath)) ? await readJson(metadataPath) : {};
  await writeJson(metadataPath, {
    schema_version: 1,
    ...previous,
    ...patch,
    updated_at: new Date().toISOString()
  });
}

export async function pollTripoTask(taskId, options = {}) {
  const { metadataPath, pollIntervalMs = 10000, onStatus } = options;

  while (true) {
    const task = await tripoRequest("GET", `/tasks/${encodeURIComponent(taskId)}`);
    const status = String(task?.status || "unknown").toLowerCase();
    const statusPatch = {
      endpoint: TRIPO_3D_ENDPOINT,
      request_id: taskId,
      status,
      progress: task?.progress,
      checked_at: new Date().toISOString()
    };
    await patchMetadata(metadataPath, statusPatch);
    if (onStatus) await onStatus(statusPatch);

    if (status === "success") return task;
    if (FAILED_STATUSES.has(status)) {
      const reason = task?.error_message || (task?.error_code ? `error code ${task.error_code}` : status);
      await patchMetadata(metadataPath, { error: reason });
      throw new Error(`Tripo task ${taskId} ${status}: ${reason}.`);
    }

    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }
}

function extensionFromUrl(url, fallback) {
  try {
    return path.extname(new URL(url).pathname) || fallback;
  } catch {
    return fallback;
  }
}

// Shape Tripo's flat `*_url` output into the `{ url, file_name }` objects downloadRemoteFiles expects.
export function tripoOutputFiles(output = {}) {
  const keys = Object.keys(output).filter((key) => key.endsWith("_url") && typeof output[key] === "string");
  keys.sort((a, b) => {
    const rank = (key) => (OUTPUT_KEY_ORDER.includes(key) ? OUTPUT_KEY_ORDER.indexOf(key) : OUTPUT_KEY_ORDER.length);
    return rank(a) - rank(b);
  });

  const files = {};
  for (const key of keys) {
    const label = key.replace(/_url$/, "");
    const fallback = label.includes("image") ? ".png" : ".glb";
    files[label] = {
      url: output[key],
      file_name: `${TRIPO_3D_PROVIDER}-${label}${extensionFromUrl(output[key], fallback)}`
    };
  }
  return files;
}

async function finishTripoTask({ task, taskId, submittedAt, image, outputDir, assetName, input, metadataPath, metadata }) {
  const files = tripoOutputFiles(task.output);
  if (Object.keys(files).length === 0) {
    throw new Error(`Tripo task ${taskId} succeeded but returned no downloadable files.`);
  }

  const downloaded = await downloadRemoteFiles(files, outputDir, TRIPO_3D_PROVIDER);
  const summary = buildRequestSummary({
    kind: "3d",
    provider: TRIPO_3D_ENDPOINT,
    metadata: { provider_slug: TRIPO_3D_PROVIDER, ...metadata },
    requestId: taskId,
    submittedAt,
    inputFiles: image ? [image] : [],
    outputFiles: downloaded.map((file) => file.path),
    downloadedFiles: downloaded,
    result: sanitizeForMetadata(task),
    extra: {
      asset_name: assetName,
      input,
      credits_consumed: task.credits_consumed
    }
  });

  await writeJson(metadataPath, summary);
  return summary;
}

export async function runTripo3D(options) {
  const {
    image,
    outputDir,
    assetName,
    metadataPath: providedMetadataPath,
    metadata = {},
    pollIntervalMs = 10000,
    onSubmit,
    onStatus
  } = options;

  if (!image) throw new Error("Input image is required.");
  if (!outputDir) throw new Error("outputDir is required.");

  await ensureDir(outputDir);
  const metadataPath = providedMetadataPath || requestPath(outputDir, 0, TRIPO_3D_PROVIDER);
  const generationInput = buildTripo3DInput(options);
  const fileInput = await uploadTripoImage(image);
  const requestBody = { ...generationInput, input: fileInput };

  const submittedAt = new Date().toISOString();
  const created = await tripoRequest("POST", "/generation/image-to-model", { body: requestBody });
  const taskId = created?.task_id;
  if (!taskId) throw new Error("Tripo submit response did not include task_id.");

  const submitted = {
    kind: "3d",
    provider: TRIPO_3D_ENDPOINT,
    provider_slug: TRIPO_3D_PROVIDER,
    ...metadata,
    endpoint: TRIPO_3D_ENDPOINT,
    request_id: taskId,
    status: "submitted",
    submitted_at: submittedAt,
    input_files: [image],
    input: requestBody
  };
  await patchMetadata(metadataPath, submitted);
  if (onSubmit) await onSubmit(submitted);

  const task = await pollTripoTask(taskId, { metadataPath, pollIntervalMs, onStatus });
  return finishTripoTask({
    task,
    taskId,
    submittedAt,
    image,
    outputDir,
    assetName,
    input: requestBody,
    metadataPath,
    metadata
  });
}

// Resume polling a Tripo task recorded in hidden request metadata.
export async function resumeTripo3D(request, outputDir, pollIntervalMs = 10000) {
  const task = await pollTripoTask(request.data.request_id, { metadataPath: request.path, pollIntervalMs });
  return finishTripoTask({
    task,
    taskId: request.data.request_id,
    submittedAt: request.data.submitted_at,
    image: request.data.input_files?.[0],
    outputDir,
    assetName: request.data.asset_name,
    input: request.data.input,
    metadataPath: request.path,
    metadata: { index: request.data.index ?? request.index }
  });
}

async function main() {
  const { flags } = parseArgs();
  const image = one(flags, "image") || one(flags, "input-image");
  const outputDir = one(flags, "output-dir");

  if (!image || !outputDir) {
    throw new Error(
      "Usage: node tripo-3d.mjs --image <path-or-url> --output-dir <dir> [--asset-name <name>] [--tripo-model v3.1-20260211] [--face-limit <n>|auto] [--texture-quality fast|standard|detailed|extreme] [--geometry-quality standard|detailed] [--enable-pbr true|false] [--texture true|false] [--smart-low-poly true|false] [--quad true|false]"
    );
  }

  const summary = await runTripo3D({
    image,
    outputDir,
    assetName: one(flags, "asset-name"),
    tripoModel: one(flags, "tripo-model", DEFAULT_TRIPO_MODEL),
    faceLimit: one(flags, "face-limit", DEFAULT_TRIPO_FACE_LIMIT),
    texture: one(flags, "texture", DEFAULT_TRIPO_TEXTURE),
    enablePbr: one(flags, "enable-pbr", DEFAULT_TRIPO_ENABLE_PBR),
    textureQuality: one(flags, "texture-quality", DEFAULT_TRIPO_TEXTURE_QUALITY),
    geometryQuality: one(flags, "geometry-quality", DEFAULT_TRIPO_GEOMETRY_QUALITY),
    smartLowPoly: one(flags, "smart-low-poly"),
    quad: one(flags, "quad"),
    orientation: one(flags, "orientation"),
    enableImageAutofix: one(flags, "enable-image-autofix")
  });

  console.log(JSON.stringify(summary, null, 2));
}

if (process.argv[1] && import.meta.url === (await import("node:url")).pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
