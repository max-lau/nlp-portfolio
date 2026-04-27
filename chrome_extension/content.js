// content.js
// Injected into all pages — captures text selection and sends to background

let lastSelection = "";

document.addEventListener("mouseup", () => {
  const selected = window.getSelection().toString().trim();
  if (selected && selected !== lastSelection && selected.length > 10) {
    lastSelection = selected;
    chrome.runtime.sendMessage({
      type: "SELECTED_TEXT",
      text: selected
    });
  }
});
