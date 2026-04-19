import katex from "katex";
import ReactMarkdown from "react-markdown";

import "katex/dist/katex.min.css";


const LATEX_MARKERS = [
  "\\mathbf",
  "\\mathcal",
  "\\mathrm",
  "\\delta",
  "\\sum",
  "\\dot",
  "\\begin",
  "\\end",
  "\\left",
  "\\right",
  "\\tag{",
  "\\leq",
  "\\geq",
  "\\frac",
  "\\bf",
  "_{",
  "^{",
];

const BLOCK_MATH_PATTERN = /(\$\$[\s\S]+?\$\$)/g;
const INLINE_MATH_PATTERN = /(\$[^$\n]+?\$)/g;


function looksLikeBareLatex(text) {
  if (!text || text.includes("$")) {
    return false;
  }

  const score = LATEX_MARKERS.reduce((count, marker) => (
    count + (text.includes(marker) ? 1 : 0)
  ), 0);

  return score >= 2;
}


function needsDisplayMath(text) {
  return (
    text.includes("\\begin") ||
    text.includes("\\tag{") ||
    text.includes("\\left\\{") ||
    text.includes("\\right.") ||
    text.includes("\\sum") ||
    text.includes("\\operatorname*")
  );
}


function compactLetters(text) {
  return text.replace(/\s+/g, "");
}


function cleanFormulaBody(formula) {
  let cleaned = formula.trim();

  cleaned = cleaned.replace(
    /\\operatorname\*\s*\{\s*(([A-Za-z]\s*)+)\}/g,
    (_, letters) => `\\operatorname*{${compactLetters(letters)}}`,
  );

  cleaned = cleaned.replace(
    /\\mathrm\s*\{\s*(([A-Za-z]\s*)+)\}/g,
    (_, letters) => `\\mathrm{${compactLetters(letters)}}`,
  );

  cleaned = cleaned.replace(
    /P\s*_\s*\{\s*(\\(?:mathbf|bf)\s*\{\s*g\s*\}\s*_\s*\{\s*[^}]+\s*\})\s*(\\(?:mathbf|bf)\s*\{\s*g\s*\}\s*_\s*\{\s*[^}]+\s*\})\s*\^\s*\{\s*\*\s*\}\s*\}/g,
    (match, firstVector, secondVector) => {
      if (compactLetters(firstVector) !== compactLetters(secondVector)) {
        return match;
      }

      return `P _ { ${firstVector} } ${secondVector} ^ { * }`;
    },
  );

  cleaned = cleaned.replace(
    /P\s*_\s*\{\s*(\\(?:mathbf|bf)\s*\{\s*g\s*\}\s*_\s*\{\s*[^}]+\s*\})\s*(\\(?:mathbf|bf)\s*\{\s*g\s*\}\s*_\s*\{\s*[^}]+\s*\})\s*\}/g,
    (match, firstVector, secondVector) => {
      if (compactLetters(firstVector) !== compactLetters(secondVector)) {
        return match;
      }

      return `P _ { ${firstVector} } ${secondVector}`;
    },
  );

  return cleaned.replace(/\s{2,}/g, " ").trim();
}


function normalizeMathText(text) {
  let normalized = text.replace(/\r\n/g, "\n");

  normalized = normalized.replace(/\$\$\s*([\s\S]+?)\s*\$\$/g, (_, formula) => (
    `\n\n$$${cleanFormulaBody(formula)}$$\n\n`
  ));

  normalized = normalized.replace(/\\\[\s*([\s\S]+?)\s*\\\]/g, (_, formula) => (
    `\n\n$$${cleanFormulaBody(formula)}$$\n\n`
  ));

  normalized = normalized.replace(/\\\(\s*([\s\S]+?)\s*\\\)/g, (_, formula) => {
    const trimmed = cleanFormulaBody(formula);
    if (needsDisplayMath(trimmed)) {
      return `\n\n$$${trimmed}$$\n\n`;
    }

    return `$${trimmed}$`;
  });

  normalized = normalized.replace(/\$([^\n$]+?)\$/g, (_, formula) => {
    const trimmed = cleanFormulaBody(formula);
    if (!trimmed || !needsDisplayMath(trimmed)) {
      return `$${trimmed}$`;
    }

    return `\n\n$$${trimmed}$$\n\n`;
  });

  normalized = normalized.replace(
    /([:：]\s*)(\\[\s\S]+?)(?=(\s+(?:where|其中|which)\b|[。；;]\s*|\n{2,}|$))/g,
    (match, prefix, formula) => {
      if (!looksLikeBareLatex(formula)) {
        return match;
      }

      return `${prefix}\n\n$$${cleanFormulaBody(formula)}$$\n\n`;
    },
  );

  normalized = normalized.replace(/([A-Za-z0-9])(\$[^$\n]+?\$)/g, "$1 $2");
  normalized = normalized.replace(/(\$[^$\n]+?\$)([A-Za-z0-9])/g, "$1 $2");
  normalized = normalized.replace(/\s{3,}/g, "  ");

  return normalized.trim();
}


function stripMathDelimiters(text) {
  const trimmed = text.trim();
  if (trimmed.startsWith("$$") && trimmed.endsWith("$$")) {
    return trimmed.slice(2, -2).trim();
  }

  if (trimmed.startsWith("$") && trimmed.endsWith("$")) {
    return trimmed.slice(1, -1).trim();
  }

  return trimmed;
}


function isSuspiciousFormula(formula, forceSuspicious = false) {
  const cleaned = cleanFormulaBody(formula);

  if (forceSuspicious || !cleaned) {
    return true;
  }

  if ((cleaned.match(/{/g) || []).length !== (cleaned.match(/}/g) || []).length) {
    return true;
  }

  if ((cleaned.match(/\(/g) || []).length !== (cleaned.match(/\)/g) || []).length) {
    return true;
  }

  if (cleaned.includes("\\begin") !== cleaned.includes("\\end")) {
    return true;
  }

  if (cleaned.includes("\\left") !== cleaned.includes("\\right")) {
    return true;
  }

  return /[_^]\s*$/.test(cleaned);
}


function renderKatex(formula, displayMode) {
  try {
    const html = katex.renderToString(cleanFormulaBody(formula), {
      displayMode,
      throwOnError: true,
      strict: "ignore",
      trust: true,
    });

    return { html, failed: false };
  } catch {
    return { html: "", failed: true };
  }
}


function buildEquationImageUrl(paperId, equationId) {
  if (!paperId || !equationId) {
    return "";
  }

  return `/api/equation-image/${encodeURIComponent(paperId)}/${encodeURIComponent(equationId)}.png`;
}


function renderInlineTokens(text, keyPrefix) {
  return text.split(INLINE_MATH_PATTERN).filter(Boolean).map((segment, index) => {
    if (segment.startsWith("$") && segment.endsWith("$")) {
      const formula = segment.slice(1, -1);
      const { html } = renderKatex(formula, false);

      if (html) {
        return (
          <span
            key={`${keyPrefix}-inline-${index}`}
            className="math-inline"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        );
      }
    }

    return (
      <ReactMarkdown
        key={`${keyPrefix}-text-${index}`}
        components={{
          p: ({ children }) => <>{children}</>,
        }}
      >
        {segment}
      </ReactMarkdown>
    );
  });
}


function renderTextBlock(block, keyPrefix) {
  const trimmed = block.trim();
  if (!trimmed) {
    return null;
  }

  const lines = trimmed.split("\n").map((line) => line.trim()).filter(Boolean);
  const bulletLines = lines.filter((line) => /^[-*]\s+/.test(line));
  const orderedLines = lines.filter((line) => /^\d+\.\s+/.test(line));

  if (lines.length > 0 && bulletLines.length === lines.length) {
    return (
      <ul key={`${keyPrefix}-list`} className="math-list">
        {lines.map((line, index) => (
          <li key={`${keyPrefix}-item-${index}`}>
            {renderInlineTokens(line.replace(/^[-*]\s+/, ""), `${keyPrefix}-item-${index}`)}
          </li>
        ))}
      </ul>
    );
  }

  if (lines.length > 0 && orderedLines.length === lines.length) {
    return (
      <ol key={`${keyPrefix}-olist`} className="math-list">
        {lines.map((line, index) => (
          <li key={`${keyPrefix}-item-${index}`}>
            {renderInlineTokens(line.replace(/^\d+\.\s+/, ""), `${keyPrefix}-item-${index}`)}
          </li>
        ))}
      </ol>
    );
  }

  return (
    <p key={`${keyPrefix}-paragraph`} className="math-paragraph">
      {renderInlineTokens(trimmed, `${keyPrefix}-paragraph`)}
    </p>
  );
}


function renderEquationFallback(block, paperId, key) {
  const imageUrl = buildEquationImageUrl(paperId, block.equation_id);
  if (!imageUrl) {
    return (
      <pre key={key} className="math-block-fallback">
        {stripMathDelimiters(block.text)}
      </pre>
    );
  }

  return (
    <figure key={key} className="equation-fallback">
      <img
        className="equation-fallback-image"
        src={imageUrl}
        alt="论文中的公式区域截图"
        loading="lazy"
      />
      <figcaption className="equation-fallback-caption">
        当前公式文本疑似损坏，已回退为 PDF 区域截图。
      </figcaption>
    </figure>
  );
}


function renderEquationBlock(block, paperId, key) {
  const formula = stripMathDelimiters(block.text);
  const forcedFallback = isSuspiciousFormula(formula, block.is_suspicious);

  if (!forcedFallback) {
    const { html, failed } = renderKatex(formula, true);
    if (html && !failed) {
      return (
        <div
          key={key}
          className="math-block-wrapper"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      );
    }
  }

  return renderEquationFallback(block, paperId, key);
}


function renderStructuredBlocks(blocks, paperId) {
  return blocks.map((block, index) => {
    if (block.block_type === "equation") {
      return renderEquationBlock(block, paperId, `equation-${index}-${block.equation_id || "raw"}`);
    }

    return renderTextBlock(block.text, `text-${index}`);
  });
}


function renderTextContent(text) {
  const normalizedText = normalizeMathText(text);
  const blocks = normalizedText.split(BLOCK_MATH_PATTERN).filter(Boolean);

  return blocks.map((block, index) => {
    if (block.startsWith("$$") && block.endsWith("$$")) {
      const formula = block.slice(2, -2);
      const { html, failed } = renderKatex(formula, true);

      if (html && !failed) {
        return (
          <div
            key={`block-${index}`}
            className="math-block-wrapper"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        );
      }

      return (
        <pre key={`block-${index}`} className="math-block-fallback">
          {formula}
        </pre>
      );
    }

    return renderTextBlock(block, `block-${index}`);
  });
}


function MathText({
  text = "",
  blocks = [],
  paperId = "",
  className = "",
}) {
  if (!text && (!blocks || blocks.length === 0)) {
    return null;
  }

  const mergedClassName = ["math-text", className].filter(Boolean).join(" ");

  return (
    <div className={mergedClassName}>
      {blocks && blocks.length > 0 ? renderStructuredBlocks(blocks, paperId) : renderTextContent(text)}
    </div>
  );
}


export default MathText;
