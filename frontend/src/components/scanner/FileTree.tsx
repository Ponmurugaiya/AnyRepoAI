"use client";

/**
 * Collapsible directory tree for the repository manifest.
 */
import { useState } from "react";
import { type DirectoryNode } from "@/lib/api-client";
import { languageColor, formatBytes } from "@/lib/utils";

interface NodeProps {
  node: DirectoryNode;
  depth: number;
}

function TreeNode({ node, depth }: NodeProps) {
  const [open, setOpen] = useState(depth < 2);

  if (node.is_file) {
    return (
      <div
        className="flex items-center gap-2 py-0.5 px-2 rounded hover:bg-gray-800 group"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <span className="text-gray-600 text-xs" aria-hidden="true">📄</span>
        <span className="text-sm text-gray-300 flex-1 font-mono truncate">{node.name}</span>
        {node.language && node.language !== "Unknown" && (
          <span
            className="text-xs px-1.5 py-0.5 rounded font-medium shrink-0"
            style={{
              backgroundColor: `${languageColor(node.language)}22`,
              color: languageColor(node.language),
            }}
          >
            {node.language}
          </span>
        )}
        {node.size_bytes != null && (
          <span className="text-xs text-gray-600 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
            {formatBytes(node.size_bytes)}
          </span>
        )}
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 py-0.5 px-2 rounded hover:bg-gray-800 text-left"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        aria-expanded={open}
      >
        <span className="text-gray-500 text-xs w-3 shrink-0" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
        <span className="text-xs" aria-hidden="true">📁</span>
        <span className="text-sm font-medium text-gray-200">{node.name}</span>
        <span className="text-xs text-gray-600 ml-auto">
          {node.children.length} items
        </span>
      </button>

      {open && (
        <div>
          {node.children.map((child) => (
            <TreeNode key={child.path} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

interface FileTreeProps {
  nodes: DirectoryNode[];
}

export function FileTree({ nodes }: FileTreeProps) {
  if (nodes.length === 0) {
    return (
      <p className="text-sm text-gray-500 py-4 text-center">
        No files to display. Run a scan first.
      </p>
    );
  }

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950 py-2 overflow-auto max-h-[600px] font-mono text-sm">
      {nodes.map((node) => (
        <TreeNode key={node.path} node={node} depth={0} />
      ))}
    </div>
  );
}
