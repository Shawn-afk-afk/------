import { readFile, readdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

const packages = JSON.parse(await readFile("package-lock.json", "utf8")).packages;
const licenses = [];
for (const [path, info] of Object.entries(packages)) {
  if (!path || info.dev || path.endsWith("/esbuild") || path.includes("/@esbuild/")) continue;
  const files = await readdir(path);
  const license = files.find(name => /^licen[cs]e(\.\w+)?$/i.test(name));
  if (!license) throw new Error(`Missing license for ${path}`);
  licenses.push(`${path.replace(/^node_modules\//, "")} ${info.version}\n\n${await readFile(join(path, license), "utf8")}`);
}
await writeFile("../static/writing/editor-deps.LICENSE.txt", licenses.join("\n\n——————————\n\n"));
