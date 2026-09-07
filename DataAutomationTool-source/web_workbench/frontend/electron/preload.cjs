const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("automationTool", {
  workerSessionSecret: () => process.env.DATA_AUTOMATION_SESSION_SECRET || "",
  selectNewTaskParentDirectory: () => ipcRenderer.invoke("select-new-task-parent-directory"),
  selectTaskDirectory: () => ipcRenderer.invoke("select-task-directory"),
  openAsinWorkbook: (taskDir) => ipcRenderer.invoke("open-asin-workbook", taskDir),
  selectInput: (kind, taskDir) => ipcRenderer.invoke("select-input", kind, taskDir),
  openOutput: (kind, taskDir) => ipcRenderer.invoke("open-output", kind, taskDir),
  saveCurl: (kind, taskDir, content) => ipcRenderer.invoke("save-curl", kind, taskDir, content),
  launchDebugChrome: () => ipcRenderer.invoke("launch-debug-chrome"),
  stopJob: (jobId) => ipcRenderer.invoke("stop-job", jobId),
  resumeJob: (jobId) => ipcRenderer.invoke("resume-job", jobId),
  restartJob: (jobId) => ipcRenderer.invoke("restart-job", jobId),
});
