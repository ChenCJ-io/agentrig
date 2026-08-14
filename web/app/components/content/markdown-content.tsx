import { useMemo, type JSX, type ReactNode } from "react";
import { defaultUrlTransform, type Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import styles from "./markdown-content.module.css";

interface MarkdownContentProps {
  content: string;
  className?: string;
  headingLevel?: 2 | 3 | 4 | 5 | 6;
}

export function MarkdownContent({
  content,
  className,
  headingLevel,
}: MarkdownContentProps) {
  const components = useMemo<Components>(() => {
    const Heading = headingLevel
      ? ({ children }: { children?: ReactNode }) => {
          const Tag = `h${headingLevel}` as keyof JSX.IntrinsicElements;
          return <Tag>{children}</Tag>;
        }
      : undefined;
    return {
      a: ({ href, children, ...props }) => (
        <a {...props} href={href} rel="noreferrer" target="_blank">
          {children}
        </a>
      ),
      ...(Heading
        ? { h1: Heading, h2: Heading, h3: Heading, h4: Heading, h5: Heading, h6: Heading }
        : {}),
    };
  }, [headingLevel]);

  return (
    <div className={[styles.markdown, className].filter(Boolean).join(" ")}>
      <ReactMarkdown
        components={components}
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={defaultUrlTransform}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
