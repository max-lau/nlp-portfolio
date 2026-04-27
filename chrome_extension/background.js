// background.js
// Service worker for NLP Legal Analyzer Chrome Extension
// Handles context menu and message passing

chrome.runtime.onInstalled.addListener(() => {
  // Right-click context menu
  chrome.contextMenus.create({
    id: "nlp-analyze",
    title: "Analyze with NLP Legal Analyzer",
    contexts: ["selection"]
  });
  chrome.contextMenus.create({
    id: "nlp-risk",
    title: "Check Risk Score",
    contexts: ["selection"]
  });
  chrome.contextMenus.create({
    id: "nlp-citations",
    title: "Extract Legal Citations",
    contexts: ["selection"]
  });
});

// Handle context menu clicks
chrome.contextMenus.onClicked.addListener((info, tab) => {
  const text = info.selectionText;
  if (!text) return;

  // Store selected text and action, open popup
  chrome.storage.local.set({
    selectedText: text,
    pendingAction: info.menuItemId
  });

  // Open popup
  chrome.action.openPopup();
});

// Handle messages from content script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "SELECTED_TEXT") {
    chrome.storage.local.set({ selectedText: message.text });
    sendResponse({ ok: true });
  }
  return true;
});
