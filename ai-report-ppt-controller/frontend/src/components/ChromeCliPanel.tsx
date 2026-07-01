export function ChromeCliPanel() {
  return (
    <section>
      <h2>Chrome CLI</h2>
      <pre className="terminal">
        {`"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="D:\\chrome-debug-profile"`}
      </pre>
    </section>
  );
}
