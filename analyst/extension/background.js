// Open the analyst chat in a movable/resizable detached window
chrome.action.onClicked.addListener(() => {
  chrome.windows.create({
    url: chrome.runtime.getURL("popup.html"),
    type: "popup",
    width: 460,
    height: 620,
    top: 100,
    left: screen.availWidth - 500,
  });
});
