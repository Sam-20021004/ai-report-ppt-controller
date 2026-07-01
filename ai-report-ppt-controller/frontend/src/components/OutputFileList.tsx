type GeneratedFile = {
  file_id?: string;
  file_name?: string;
  file_type?: string;
  size?: number;
};

function formatSize(size = 0) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function OutputFileList({ files }: { files: Record<string, unknown>[] }) {
  const items = files as GeneratedFile[];

  return (
    <section className="status-card">
      <h2>输出文件</h2>
      <div className="file-list">
        {items.length === 0 ? <p>暂无生成文件。</p> : null}
        {items.map((file) => (
          <div className="file-item" key={file.file_id || file.file_name}>
            <div>
              {file.file_id ? (
                <a href={`/api/download/${file.file_id}`}>{file.file_name}</a>
              ) : (
                <strong>{file.file_name}</strong>
              )}
              <p>{file.file_type || "file"} · {formatSize(file.size)}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
