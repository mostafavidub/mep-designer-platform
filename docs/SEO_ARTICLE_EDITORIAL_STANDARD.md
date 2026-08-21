# EngiTools SEO Article Editorial Standard

This document is the persistent, mandatory definition of done for every new or materially revised EngiTools article. Publication must stop if any required item is missing.

## 1. Research and intent

- Re-check the live SERP immediately before drafting. Record the target query, search intent, related questions, current ranking formats, and the most useful competing pages.
- Do not reuse stale keyword-volume or competitor conclusions without verifying them.
- Identify the specific reader, their engineering decision, and the practical result the article must help them reach.
- Find a defensible content gap. The article must add value beyond paraphrasing the current results.
- Verify claims against current primary or authoritative sources. Link externally only where the source helps the reader verify a material claim.

## 2. People-first, humanized writing

- Write for a Persian-speaking building owner, architect, technician, or MEP engineer—not for a search crawler.
- Open with the reader's real problem and answer it directly. Use natural Persian, varied sentence length, concrete transitions, and terminology the audience actually uses.
- Add original EngiTools insight: a real workflow observation, a technically sound example, a limitation discovered in plan analysis, or an anonymized product example. Never invent project results, customer quotes, statistics, or field experience.
- Explain uncertainty and boundaries honestly. Preliminary automated calculations must never be presented as construction-ready or professionally approved.
- A human technical reviewer must check accuracy, usefulness, tone, and unsupported claims before publication.
- Prohibited: keyword stuffing, spun or duplicated passages, thin pages, generic filler, fake firsthand experience, fabricated citations, mass-produced doorway pages, or spammy AI content created mainly to manipulate rankings.

## 3. Page structure and metadata

- Exactly one descriptive H1.
- Use logical H2 sections and H3 subsections only when they clarify hierarchy; never skip levels for styling.
- Create a unique, intent-matched title, meta description, and short stable slug. Check the repository and live site for duplicates.
- Provide a self-referencing HTTPS canonical and index/follow robots unless a documented noindex decision exists.
- Use valid Article schema with at least headline, description, image, author/publisher, language, and mainEntityOfPage. Add other schema only when the visible page genuinely supports it.
- Keep paragraphs and sections scannable on mobile. Avoid dense walls of text, oversized tables, overflow, and unexplained English jargon.

## 4. Links and calls to action

- Add contextual internal links to relevant service pages and related articles. Use descriptive anchor text; do not force exact-match anchors repeatedly.
- Add selective external links to authoritative primary sources for claims readers may need to verify. Do not add decorative or low-quality outbound links.
- Use no more than two CTA boxes per article.
- Place a CTA naturally after roughly three to four substantive paragraphs or at a real decision point. Do not interrupt the introduction or place CTAs back-to-back.
- Match the CTA to the article: Electrical, Mechanical, or Architect. Do not link to an unfinished/noindex service unless the CTA clearly describes its availability.

## 5. Visual standard

Each article requires five original visual assets at minimum:

1. One separate featured image, normally 16:9, optimized for the web.
2. At least four original in-article visuals that teach or clarify distinct points.

Requirements:

- The featured image must render near the article header and be used by Open Graph, Twitter/X, and Article schema.
- Every image needs a specific Persian alt describing its visible content and purpose. Never use a keyword list or repeat the caption verbatim when that adds no value.
- Decorative images use empty alt text; educational article visuals are not decorative.
- Store assets under the article's static asset path with stable, descriptive filenames.
- Provide intrinsic dimensions, responsive sizing, and modern compression. The featured/LCP image must not be lazy-loaded; below-the-fold visuals should be lazy-loaded.
- Confirm visual originality and technical plausibility. Do not use generated diagrams as proof of a real project.

## 6. Technical and editorial verification

Before merge:

- Verify the engineering claims, units, terminology, standards references, calculations, and limitations.
- Confirm one H1; logical headings; unique title, meta, slug; canonical; robots; Article schema; featured-image metadata; and descriptive alt text for every meaningful image.
- Confirm at least four inline visuals plus one separate featured image.
- Confirm zero to two CTA boxes, with natural spacing and relevant destinations.
- Check internal links, external links, broken URLs, and redirect chains.
- Check responsive rendering at narrow mobile and desktop widths, RTL layout, line length, contrast, image aspect ratios, and page readability.
- Run the automated test suite and the repository's on-page SEO audit. Resolve failures rather than suppressing them.

## 7. Deployment, audit, and indexing workflow

1. Work on a reviewable branch and preserve unrelated changes.
2. Run tests and on-page SEO checks locally or in CI.
3. Merge only after the checklist passes.
4. Confirm the Railway deployment succeeds for the merged commit.
5. Check the production article returns HTTP 200 and `/system_health` returns HTTP 200 with required services healthy.
6. Re-run the on-page SEO audit against the production URL, including rendered HTML and social metadata.
7. Add the canonical URL to the indexing tracker or sitemap workflow and request indexing through the authorized Google Search Console process when available.
8. Never report an article as indexed merely because it was submitted. Report “indexed” only after URL Inspection confirms it.
9. Record publication date, canonical URL, target query, audit result, deployment commit, and indexing status.

## Pull-request checklist

- [ ] Fresh SERP and competitor research completed
- [ ] Search intent and unique EngiTools contribution documented
- [ ] Technical claims and limitations verified by a human reviewer
- [ ] People-first Persian copy; no stuffing, thin, duplicate, or spammy AI content
- [ ] One H1; logical H2/H3 hierarchy
- [ ] Unique title, meta description, and slug
- [ ] Canonical, robots, and valid Article schema
- [ ] Contextual internal links and useful authoritative external links
- [ ] No more than two naturally placed, topic-matched CTA boxes
- [ ] At least four original inline visuals with descriptive alt text
- [ ] One separate featured image with descriptive alt, header rendering, OG/Twitter use, and schema image
- [ ] Mobile/RTL/readability and image-performance checks passed
- [ ] Tests and on-page SEO audit passed
- [ ] Railway deployment and production `/system_health` verified
- [ ] Canonical URL entered in the indexing workflow; status reported accurately
