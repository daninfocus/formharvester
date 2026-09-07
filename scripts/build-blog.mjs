#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const SITE_URL = 'https://formharvester.com';

function parseFrontmatter(rawContent) {
  const match = rawContent.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!match) return { frontmatter: {}, body: rawContent };
  const yaml = match[1];
  const body = match[2];
  const frontmatter = {};

  for (const line of yaml.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const colon = trimmed.indexOf(':');
    if (colon === -1) continue;
    const key = trimmed.slice(0, colon).trim();
    let val = trimmed.slice(colon + 1).trim();

    if (val.startsWith('[') && val.endsWith(']')) {
      val = val.slice(1, -1).split(',').map(s => s.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
    } else if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    } else if (val === 'true') {
      val = true;
    } else if (val === 'false') {
      val = false;
    }
    frontmatter[key] = val;
  }
  return { frontmatter, body };
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function markdownToHtml(md) {
  const lines = md.split(/\r?\n/);
  const out = [];
  let inList = false;
  let inOrderedList = false;
  let inCodeBlock = false;
  let codeBuffer = [];
  let inTable = false;
  let tableHeader = true;

  function inlineFormat(text) {
    let res = escapeHtml(text);
    res = res.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
    res = res.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    res = res.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    res = res.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="prose-link">$1</a>');
    return res;
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        out.push(`<pre class="code-block"><code>${escapeHtml(codeBuffer.join('\n'))}</code></pre>`);
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        if (inList) { out.push('</ul>'); inList = false; }
        if (inOrderedList) { out.push('</ol>'); inOrderedList = false; }
        if (inTable) { out.push('</tbody></table></div>'); inTable = false; }
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      continue;
    }

    if (trimmed.startsWith('|')) {
      if (inList) { out.push('</ul>'); inList = false; }
      if (inOrderedList) { out.push('</ol>'); inOrderedList = false; }
      if (!inTable) {
        inTable = true;
        tableHeader = true;
        out.push('<div class="table-wrapper"><table class="blog-table">');
      }
      if (trimmed.includes('---')) {
        tableHeader = false;
        continue;
      }
      const cells = trimmed.split('|').slice(1, -1).map(c => c.trim());
      if (tableHeader) {
        out.push('<thead><tr>' + cells.map(c => `<th>${inlineFormat(c)}</th>`).join('') + '</tr></thead><tbody>');
      } else {
        out.push('<tr>' + cells.map(c => `<td>${inlineFormat(c)}</td>`).join('') + '</tr>');
      }
      continue;
    } else if (inTable) {
      out.push('</tbody></table></div>');
      inTable = false;
    }

    const olMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
    if (olMatch) {
      if (inList) { out.push('</ul>'); inList = false; }
      if (!inOrderedList) {
        inOrderedList = true;
        out.push('<ol class="blog-ol">');
      }
      out.push(`<li>${inlineFormat(olMatch[2])}</li>`);
      continue;
    } else if (inOrderedList) {
      out.push('</ol>');
      inOrderedList = false;
    }

    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      if (!inList) {
        inList = true;
        out.push('<ul class="blog-ul">');
      }
      out.push(`<li>${inlineFormat(trimmed.slice(2))}</li>`);
      continue;
    } else if (inList) {
      out.push('</ul>');
      inList = false;
    }

    if (trimmed.startsWith('### ')) {
      out.push(`<h3>${inlineFormat(trimmed.slice(4))}</h3>`);
      continue;
    }
    if (trimmed.startsWith('## ')) {
      out.push(`<h2>${inlineFormat(trimmed.slice(3))}</h2>`);
      continue;
    }
    if (trimmed.startsWith('# ')) {
      out.push(`<h1>${inlineFormat(trimmed.slice(2))}</h1>`);
      continue;
    }

    if (!trimmed) continue;

    out.push(`<p>${inlineFormat(trimmed)}</p>`);
  }

  if (inList) out.push('</ul>');
  if (inOrderedList) out.push('</ol>');
  if (inTable) out.push('</tbody></table></div>');
  if (inCodeBlock) out.push(`<pre class="code-block"><code>${escapeHtml(codeBuffer.join('\n'))}</code></pre>`);

  return out.join('\n');
}

function loadPosts() {
  const blogDir = path.join(process.cwd(), 'content', 'blog');
  if (!fs.existsSync(blogDir)) return [];

  const files = fs.readdirSync(blogDir).filter(f => f.endsWith('.md'));
  const posts = [];

  for (const file of files) {
    const slug = file.replace(/\.md$/, '');
    const raw = fs.readFileSync(path.join(blogDir, file), 'utf8');
    const { frontmatter, body } = parseFrontmatter(raw);
    if (frontmatter.draft) continue;

    posts.push({
      slug,
      title: frontmatter.title || slug,
      description: frontmatter.description || '',
      date: String(frontmatter.date || ''),
      updated: frontmatter.updated ? String(frontmatter.updated) : undefined,
      author: frontmatter.author || 'FormHarvester Editorial',
      tags: Array.isArray(frontmatter.tags) ? frontmatter.tags : [],
      draft: Boolean(frontmatter.draft),
      canonical: frontmatter.canonical || `${SITE_URL}/blog/${slug}/`,
      content: body,
      contentHtml: markdownToHtml(body),
    });
  }

  return posts.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
}

function renderHeader() {
  return `
  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="/">
        <img src="/logo.png" alt="FormHarvester" width="34" height="38" />
        <span><span class="brand-f">F</span>ormHarvester</span>
      </a>
      <div class="top-links">
        <a href="/">Home</a>
        <a href="/docs/">Docs</a>
        <a href="/blog/" style="color: var(--accent); font-weight: 700;">Blog</a>
        <a href="https://github.com/dariomory/formharvester" target="_blank" rel="noopener noreferrer">GitHub</a>
      </div>
    </div>
  </header>`;
}

function renderFooter() {
  return `
  <footer class="site-footer">
    <div class="footer-inner">
      <p><span style="color: var(--accent); font-weight: 700;">FormHarvester</span> — automated form intelligence & technology detection engine.</p>
      <div class="footer-links">
        <a href="/">Home</a>
        <a href="/docs/">Docs</a>
        <a href="/blog/">Blog</a>
        <a href="/rss.xml">RSS</a>
        <a href="https://github.com/dariomory/formharvester" target="_blank" rel="noopener noreferrer">Source</a>
      </div>
    </div>
  </footer>`;
}

function commonStyles() {
  return `
    :root {
      color-scheme: dark;
      --bg: #08090c;
      --panel: #0e1117;
      --panel-2: #141922;
      --fg: #e7e9ee;
      --muted: #8b93a2;
      --faint: #596170;
      --accent: #8ecbff;
      --green: #a7e3bd;
      --yellow: #f0d99a;
      --border: #202632;
      --max: 960px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--fg);
      font: 15px/1.7 ui-monospace, "SFMono-Regular", Consolas, monospace;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { color: #c8eaff; text-decoration: underline; }

    .site-header {
      border-bottom: 1px solid var(--border);
      background: rgba(8, 9, 12, 0.94);
      position: sticky; top: 0; z-index: 10;
      backdrop-filter: blur(12px);
    }
    .header-inner {
      max-width: var(--max);
      margin: 0 auto;
      padding: 0 1.25rem;
      min-height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .brand { display: flex; align-items: center; gap: 0.65rem; color: var(--fg); font-weight: 700; text-decoration: none; }
    .brand img { width: 30px; height: 34px; object-fit: contain; }
    .brand-f { color: var(--accent); }
    .top-links { display: flex; gap: 1.25rem; font-size: 0.85rem; }

    main.content {
      max-width: var(--max);
      width: 100%;
      margin: 0 auto;
      padding: 3.5rem 1.25rem 6rem;
      flex: 1;
    }

    .eyebrow {
      color: var(--accent);
      font-size: 0.78rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      margin-bottom: 0.75rem;
    }

    .blog-header { margin-bottom: 3.5rem; }
    .blog-header h1 { font-size: clamp(2rem, 4.5vw, 3.2rem); margin-bottom: 0.8rem; letter-spacing: -0.03em; }
    .blog-header p.lede { color: var(--muted); font-size: 1.05rem; max-width: 65ch; }

    .blog-card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 2rem;
      margin-bottom: 1.75rem;
      transition: border-color 0.2s;
    }
    .blog-card:hover { border-color: var(--accent); }
    .card-meta { display: flex; align-items: center; gap: 0.6rem; color: var(--muted); font-size: 0.82rem; margin-bottom: 0.75rem; }
    .blog-card h2 { font-size: 1.45rem; line-height: 1.3; margin-bottom: 0.75rem; }
    .blog-card h2 a { color: var(--fg); }
    .blog-card h2 a:hover { color: var(--accent); }
    .blog-card p { color: var(--muted); font-size: 0.95rem; margin-bottom: 1.25rem; }
    .card-footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.75rem; border-top: 1px solid var(--border); padding-top: 1rem; }
    .tags { display: flex; flex-wrap: wrap; gap: 0.4rem; }
    .tag { font-size: 0.75rem; color: var(--muted); background: var(--panel-2); border: 1px solid var(--border); padding: 0.2rem 0.5rem; border-radius: 4px; }
    .read-link { font-size: 0.85rem; font-weight: 700; color: var(--accent); }

    /* Single Post */
    .breadcrumbs { display: flex; gap: 0.5rem; color: var(--faint); font-size: 0.8rem; margin-bottom: 1.5rem; }
    .breadcrumbs a { color: var(--muted); }
    .post-header { margin-bottom: 2.5rem; border-bottom: 1px solid var(--border); padding-bottom: 2rem; }
    .post-header h1 { font-size: clamp(1.9rem, 4.5vw, 2.9rem); line-height: 1.2; margin: 0.75rem 0; }
    .post-lede { color: var(--muted); font-size: 1.1rem; }

    .prose { font-size: 1rem; line-height: 1.8; color: var(--fg); }
    .prose h2 { font-size: 1.55rem; margin: 3rem 0 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; color: #fff; }
    .prose h3 { font-size: 1.15rem; margin: 2rem 0 0.6rem; color: #cfd5df; }
    .prose p { margin-bottom: 1.5rem; }
    .prose ul.blog-ul, .prose ol.blog-ol { margin: 0 0 1.5rem 1.5rem; }
    .prose li { margin-bottom: 0.5rem; }
    .prose strong { color: #fff; }
    .inline-code { color: #cde9ff; background: #10141c; border: 1px solid var(--border); border-radius: 4px; padding: 0.15rem 0.4rem; font-size: 0.88em; }
    .code-block { background: #0e1117; border: 1px solid var(--border); border-radius: 6px; padding: 1.25rem; margin: 1.75rem 0; overflow-x: auto; font-size: 0.88rem; line-height: 1.55; color: #d4e7f7; }
    .table-wrapper { overflow-x: auto; margin: 2rem 0; border: 1px solid var(--border); border-radius: 6px; }
    .blog-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; text-align: left; }
    .blog-table th { background: var(--panel); padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); color: #fff; }
    .blog-table td { padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); color: var(--muted); }
    .blog-table tr:last-child td { border-bottom: none; }

    .author-box { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 1.5rem; margin-top: 3.5rem; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem; }
    .author-box h3 { font-size: 1rem; margin-bottom: 0.25rem; }
    .author-box p { color: var(--muted); font-size: 0.85rem; }

    .site-footer { border-top: 1px solid var(--border); padding: 2.5rem 1.25rem; color: var(--muted); font-size: 0.82rem; }
    .footer-inner { max-width: var(--max); margin: 0 auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem; }
    .footer-links { display: flex; gap: 1rem; }
  `;
}

function generateBlogIndex(posts) {
  const structuredData = {
    "@context": "https://schema.org",
    "@type": "Blog",
    "name": "FormHarvester Blog",
    "description": "Technical articles, architecture deep dives, and heuristics on web form extraction, technology fingerprinting, and browser automation.",
    "url": `${SITE_URL}/blog/`,
    "blogPost": posts.map(p => ({
      "@type": "BlogPosting",
      "headline": p.title,
      "description": p.description,
      "datePublished": p.date,
      "url": `${SITE_URL}/blog/${p.slug}/`,
      "author": {
        "@type": "Organization",
        "name": p.author
      }
    }))
  };

  const cardsHtml = posts.map(post => `
    <article class="blog-card">
      <div class="card-meta">
        <time datetime="${post.date}">${new Date(post.date).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</time>
        <span>•</span>
        <span>${escapeHtml(post.author)}</span>
      </div>
      <h2><a href="/blog/${post.slug}/">${escapeHtml(post.title)}</a></h2>
      <p>${escapeHtml(post.description)}</p>
      <div class="card-footer">
        <div class="tags">
          ${post.tags.map(t => `<span class="tag">#${escapeHtml(t)}</span>`).join('')}
        </div>
        <a class="read-link" href="/blog/${post.slug}/">Read article &rarr;</a>
      </div>
    </article>
  `).join('');

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Blog — FormHarvester Engineering</title>
<meta name="description" content="Technical articles, architecture deep dives, and heuristics on web form extraction, technology fingerprinting, and browser automation." />
<link rel="canonical" href="${SITE_URL}/blog/" />
<meta name="theme-color" content="#08090c" />
<link rel="icon" href="/logo.png" type="image/png" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="FormHarvester" />
<meta property="og:title" content="Blog — FormHarvester Engineering" />
<meta property="og:description" content="Technical articles on automated web form extraction and technology detection." />
<meta property="og:url" content="${SITE_URL}/blog/" />
<meta property="og:image" content="${SITE_URL}/logo.jpeg" />
<meta name="twitter:card" content="summary_large_image" />
<script type="application/ld+json">
${JSON.stringify(structuredData)}
</script>
<style>${commonStyles()}</style>
</head>
<body>
  ${renderHeader()}
  <main class="content">
    <header class="blog-header">
      <p class="eyebrow">Engineering & Research</p>
      <h1>Notes on form extraction</h1>
      <p class="lede">Deep dives into heuristic web discovery, DOM parsing pipelines, technology fingerprinting, and headless browser automation.</p>
    </header>
    <div class="blog-list">
      ${cardsHtml}
    </div>
  </main>
  ${renderFooter()}
</body>
</html>`;
}

function generateBlogPost(post) {
  const structuredData = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": post.title,
    "description": post.description,
    "datePublished": post.date,
    ...(post.updated ? { "dateModified": post.updated } : {}),
    "url": `${SITE_URL}/blog/${post.slug}/`,
    "author": {
      "@type": "Organization",
      "name": post.author,
      "url": SITE_URL
    },
    "publisher": {
      "@type": "Organization",
      "name": "FormHarvester",
      "url": SITE_URL
    },
    "mainEntityOfPage": {
      "@type": "WebPage",
      "@id": `${SITE_URL}/blog/${post.slug}/`
    }
  };

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${escapeHtml(post.title)} — FormHarvester Blog</title>
<meta name="description" content="${escapeHtml(post.description)}" />
<link rel="canonical" href="${post.canonical}" />
<meta name="theme-color" content="#08090c" />
<link rel="icon" href="/logo.png" type="image/png" />
<meta property="og:type" content="article" />
<meta property="og:site_name" content="FormHarvester" />
<meta property="og:title" content="${escapeHtml(post.title)}" />
<meta property="og:description" content="${escapeHtml(post.description)}" />
<meta property="og:url" content="${SITE_URL}/blog/${post.slug}/" />
<meta property="og:image" content="${SITE_URL}/logo.jpeg" />
<meta name="twitter:card" content="summary_large_image" />
<script type="application/ld+json">
${JSON.stringify(structuredData)}
</script>
<style>${commonStyles()}</style>
</head>
<body>
  ${renderHeader()}
  <main class="content">
    <article>
      <nav class="breadcrumbs" aria-label="Breadcrumb">
        <a href="/">Home</a>
        <span>/</span>
        <a href="/blog/">Blog</a>
        <span>/</span>
        <span style="color: var(--fg);">${escapeHtml(post.title)}</span>
      </nav>

      <header class="post-header">
        <p class="eyebrow">Form Intelligence Architecture</p>
        <h1>${escapeHtml(post.title)}</h1>
        <div class="card-meta">
          <time datetime="${post.date}">${new Date(post.date).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</time>
          <span>•</span>
          <span style="color: var(--fg); font-weight: 700;">${escapeHtml(post.author)}</span>
          ${post.updated ? `<span>•</span><span style="font-style: italic;">Updated ${new Date(post.updated).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</span>` : ''}
        </div>
        <p class="post-lede">${escapeHtml(post.description)}</p>
        ${post.tags.length > 0 ? `
          <div class="tags" style="margin-top: 1rem;">
            ${post.tags.map(t => `<span class="tag">#${escapeHtml(t)}</span>`).join('')}
          </div>` : ''}
      </header>

      <div class="prose">
        ${post.contentHtml}
      </div>

      <div class="author-box">
        <div>
          <h3>Published by ${escapeHtml(post.author)}</h3>
          <p>FormHarvester is an open-source engine for web discovery, contact extraction, and website technology detection.</p>
        </div>
        <a href="/blog/" style="font-weight: 700;">All articles &rarr;</a>
      </div>
    </article>
  </main>
  ${renderFooter()}
</body>
</html>`;
}

function generateRss(posts) {
  const items = posts.map(p => `
    <item>
      <title><![CDATA[${p.title}]]></title>
      <link>${SITE_URL}/blog/${p.slug}/</link>
      <guid isPermaLink="true">${SITE_URL}/blog/${p.slug}/</guid>
      <description><![CDATA[${p.description}]]></description>
      <pubDate>${new Date(p.date).toUTCString()}</pubDate>
      <author>team@formharvester.com (${p.author})</author>
    </item>
  `).join('');

  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>FormHarvester Blog</title>
    <link>${SITE_URL}/blog/</link>
    <description>Technical articles on web form extraction, technology detection, and browser automation.</description>
    <language>en</language>
    <atom:link href="${SITE_URL}/rss.xml" rel="self" type="application/rss+xml" />
    ${items}
  </channel>
</rss>`.trim();
}

function generateSitemap(posts) {
  const staticUrls = [
    { loc: `${SITE_URL}/`, priority: '1.0', changefreq: 'weekly' },
    { loc: `${SITE_URL}/docs/`, priority: '0.9', changefreq: 'monthly' },
    { loc: `${SITE_URL}/blog/`, priority: '0.8', changefreq: 'weekly' },
  ];

  const postUrls = posts.map(p => ({
    loc: `${SITE_URL}/blog/${p.slug}/`,
    priority: '0.8',
    changefreq: 'monthly',
  }));

  const allUrls = [...staticUrls, ...postUrls];

  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${allUrls.map(u => `  <url>
    <loc>${u.loc}</loc>
    <changefreq>${u.changefreq}</changefreq>
    <priority>${u.priority}</priority>
  </url>`).join('\n')}
</urlset>`.trim();
}

function generateRobots() {
  return `User-agent: *
Allow: /

User-agent: GPTBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: OAI-SearchBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: Claude-User
Allow: /

User-agent: Claude-SearchBot
Allow: /

User-agent: anthropic-ai
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Perplexity-User
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: Applebot-Extended
Allow: /

User-agent: Bingbot
Allow: /

User-agent: CCBot
Allow: /

User-agent: cohere-ai
Allow: /

User-agent: Meta-ExternalAgent
Allow: /

User-agent: Amazonbot
Allow: /

User-agent: Bytespider
Allow: /

User-agent: Diffbot
Allow: /

User-agent: ImagesiftBot
Allow: /

User-agent: Omgili
Allow: /

User-agent: YouBot
Allow: /

Sitemap: https://formharvester.com/sitemap.xml
`.trim();
}

function generateLlms() {
  return `# FormHarvester

> FormHarvester is an open-source Python tool and library for automated contact page discovery, website technology detection, and browser-driven form extraction and submission.

## Blog & Engineering Articles

- [Automated Form Intelligence: Heuristic Discovery and DOM Extraction Pipelines](https://formharvester.com/blog/automated-form-intelligence-heuristic-discovery/): An architectural guide to automated web contact page discovery, DOM form extraction heuristics, website technology fingerprinting, and browser automation.
- [Blog Index](https://formharvester.com/blog/): All engineering articles, scraping heuristics, and architecture notes.

## Key Pages

- [Homepage](https://formharvester.com/): Product overview and downloads for Windows and Linux.
- [Documentation](https://formharvester.com/docs/): Python CLI usage, API reference, technology detection, and workflows.
- [RSS Feed](https://formharvester.com/rss.xml): RSS 2.0 feed of all published engineering articles.
`.trim();
}

function build() {
  console.log('Building FormHarvester blog...');
  const posts = loadPosts();
  console.log(`Found ${posts.length} blog post(s).`);

  const docsDir = path.join(process.cwd(), 'docs');
  const blogDir = path.join(docsDir, 'blog');
  if (!fs.existsSync(blogDir)) fs.mkdirSync(blogDir, { recursive: true });

  // 1. Output blog index
  fs.writeFileSync(path.join(blogDir, 'index.html'), generateBlogIndex(posts), 'utf8');
  console.log('✓ Wrote docs/blog/index.html');

  // 2. Output each post
  for (const post of posts) {
    const postDir = path.join(blogDir, post.slug);
    if (!fs.existsSync(postDir)) fs.mkdirSync(postDir, { recursive: true });
    fs.writeFileSync(path.join(postDir, 'index.html'), generateBlogPost(post), 'utf8');
    console.log(`✓ Wrote docs/blog/${post.slug}/index.html`);
  }

  // 3. Output RSS
  fs.writeFileSync(path.join(docsDir, 'rss.xml'), generateRss(posts), 'utf8');
  console.log('✓ Wrote docs/rss.xml');

  // 4. Output Sitemap
  fs.writeFileSync(path.join(docsDir, 'sitemap.xml'), generateSitemap(posts), 'utf8');
  console.log('✓ Wrote docs/sitemap.xml');

  // 5. Output Robots.txt
  fs.writeFileSync(path.join(docsDir, 'robots.txt'), generateRobots(), 'utf8');
  console.log('✓ Wrote docs/robots.txt');

  // 6. Output llms.txt
  fs.writeFileSync(path.join(docsDir, 'llms.txt'), generateLlms(), 'utf8');
  console.log('✓ Wrote docs/llms.txt');

  console.log('FormHarvester blog build complete!');
}

build();
