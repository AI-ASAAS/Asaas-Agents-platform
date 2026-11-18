import React from 'react';
import { safeHref } from '../lib/safeHref';

interface SafeMarkdownProps {
  content: string;
  className?: string;
}

/**
 * Safely renders markdown into native React virtual DOM nodes.
 * NEVER uses dangerouslySetInnerHTML or innerHTML.
 * All links are strictly validated via safeHref.
 */
export function SafeMarkdown({ content, className }: SafeMarkdownProps) {
  if (!content) return null;

  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeBlockLines: string[] = [];
  let codeBlockLang = '';

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Code block toggle ```
    if (line.trim().startsWith('```')) {
      if (inCodeBlock) {
        // End code block
        elements.push(
          <pre
            key={`code-${i}`}
            data-language={codeBlockLang || undefined}
            style={{
              padding: '12px 16px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--glass-inset)',
              overflowX: 'auto',
              fontFamily: 'monospace',
              fontSize: '13px',
              direction: 'ltr',
              textAlign: 'left',
              border: '1px solid var(--hairline)',
              margin: '10px 0',
            }}
          >
            <code>{codeBlockLines.join('\n')}</code>
          </pre>
        );
        codeBlockLines = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
        codeBlockLang = line.trim().slice(3).trim();
      }
      continue;
    }

    if (inCodeBlock) {
      codeBlockLines.push(line);
      continue;
    }

    // Blank lines
    if (!line.trim()) {
      continue;
    }

    // Headings
    if (line.startsWith('### ')) {
      elements.push(
        <h4 key={`h4-${i}`} style={{ margin: '14px 0 6px 0', fontSize: '16px', fontWeight: 700 }}>
          {renderInline(line.slice(4))}
        </h4>
      );
      continue;
    }
    if (line.startsWith('## ')) {
      elements.push(
        <h3 key={`h3-${i}`} style={{ margin: '16px 0 8px 0', fontSize: '18px', fontWeight: 700 }}>
          {renderInline(line.slice(3))}
        </h3>
      );
      continue;
    }
    if (line.startsWith('# ')) {
      elements.push(
        <h2 key={`h2-${i}`} style={{ margin: '18px 0 10px 0', fontSize: '20px', fontWeight: 700 }}>
          {renderInline(line.slice(2))}
        </h2>
      );
      continue;
    }

    // Blockquote
    if (line.startsWith('> ')) {
      elements.push(
        <blockquote
          key={`bq-${i}`}
          style={{
            borderInlineStart: '3px solid var(--accent)',
            margin: '8px 0',
            paddingInlineStart: '12px',
            color: 'var(--text-2)',
            fontStyle: 'italic',
          }}
        >
          {renderInline(line.slice(2))}
        </blockquote>
      );
      continue;
    }

    // Unordered list item
    if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
      const itemText = line.trim().slice(2);
      elements.push(
        <li key={`li-${i}`} style={{ margin: '4px 0', paddingInlineStart: '4px' }}>
          {renderInline(itemText)}
        </li>
      );
      continue;
    }

    // Numbered list item
    const numMatch = line.trim().match(/^(\d+)\.\s+(.*)$/);
    if (numMatch) {
      elements.push(
        <li key={`oli-${i}`} style={{ margin: '4px 0', paddingInlineStart: '4px' }}>
          {renderInline(numMatch[2])}
        </li>
      );
      continue;
    }

    // Normal paragraph
    elements.push(
      <p key={`p-${i}`} style={{ margin: '6px 0', lineHeight: 1.65 }}>
        {renderInline(line)}
      </p>
    );
  }

  // Handle unclosed code block if streaming ended mid-block
  if (inCodeBlock && codeBlockLines.length > 0) {
    elements.push(
      <pre
        key="code-unclosed"
        style={{
          padding: '12px 16px',
          borderRadius: 'var(--radius-md)',
          background: 'var(--glass-inset)',
          overflowX: 'auto',
          fontFamily: 'monospace',
          fontSize: '13px',
          direction: 'ltr',
          textAlign: 'left',
          border: '1px solid var(--hairline)',
        }}
      >
        <code>{codeBlockLines.join('\n')}</code>
      </pre>
    );
  }

  return <div className={`safe-markdown ${className || ''}`}>{elements}</div>;
}

/**
 * Parses inline formatting: bold (**), italic (*), inline code (`), and links ([text](url)).
 */
function renderInline(text: string): React.ReactNode {
  // Regex to match code, bold, links, italic
  const parts: React.ReactNode[] = [];
  const regex = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;

  let lastIdx = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push(text.slice(lastIdx, match.index));
    }

    const token = match[0];
    const key = `inline-${match.index}`;

    if (token.startsWith('`') && token.endsWith('`')) {
      parts.push(
        <code
          key={key}
          style={{
            padding: '2px 6px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--glass-inset)',
            fontFamily: 'monospace',
            fontSize: '0.9em',
            direction: 'ltr',
            display: 'inline-block',
          }}
        >
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith('**') && token.endsWith('**')) {
      parts.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('*') && token.endsWith('*')) {
      parts.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith('[') && token.includes('](')) {
      const closeBracket = token.indexOf('](');
      const linkText = token.slice(1, closeBracket);
      const linkUrl = token.slice(closeBracket + 2, -1);
      const sanitized = safeHref(linkUrl);
      parts.push(
        <a
          key={key}
          href={sanitized}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: 'var(--accent)', textDecoration: 'underline' }}
        >
          {linkText}
        </a>
      );
    } else {
      parts.push(token);
    }

    lastIdx = regex.lastIndex;
  }

  if (lastIdx < text.length) {
    parts.push(text.slice(lastIdx));
  }

  return parts;
}
