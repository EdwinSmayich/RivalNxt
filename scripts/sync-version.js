const fs = require("fs");
const path = require("path");

// Read version from package.json
const packageJson = require("../package.json");
const version = packageJson.version;

console.log(`📦 Syncing version ${version} to all files...`);

// 1. Update Tauri config
const tauriConfigPath = path.join(__dirname, "../src-tauri/tauri.conf.json");
const tauriConfig = JSON.parse(fs.readFileSync(tauriConfigPath, "utf8"));
tauriConfig.version = version;
fs.writeFileSync(tauriConfigPath, JSON.stringify(tauriConfig, null, 2) + "\n");
console.log(`  ✅ tauri.conf.json`);

// 2. Update core/nexus/nexus_api.py
const nexusApiPath = path.join(__dirname, "../core/nexus/nexus_api.py");
let nexusApiContent = fs.readFileSync(nexusApiPath, "utf8");
nexusApiContent = nexusApiContent.replace(
  /APP_VERSION = ["'][\d.]+["']/,
  `APP_VERSION = "${version}"`
);
fs.writeFileSync(nexusApiPath, nexusApiContent);
console.log(`  ✅ core/nexus/nexus_api.py`);

// 3. Update core/api/server.py (3 locations)
const serverPath = path.join(__dirname, "../core/api/server.py");
let serverContent = fs.readFileSync(serverPath, "utf8");

// Replace FastAPI version
serverContent = serverContent.replace(
  /app = FastAPI\(title="Mod Manager Backend", version="[\d.]+"\)/,
  `app = FastAPI(title="Mod Manager Backend", version="${version}")`
);

// Replace User-Agent in search function
serverContent = serverContent.replace(
  /"User-Agent": "Project_ModManager_Rivals\/[\d.]+"/g,
  `"User-Agent": "Project_ModManager_Rivals/${version}"`
);

// Replace Application-Version header
serverContent = serverContent.replace(
  /headers\["Application-Version"\] = "[\d.]+"/,
  `headers["Application-Version"] = "${version}"`
);

fs.writeFileSync(serverPath, serverContent);
console.log(`  ✅ core/api/server.py (3 locations)`);

console.log(`\n✨ Version sync complete! All files updated to ${version}`);
