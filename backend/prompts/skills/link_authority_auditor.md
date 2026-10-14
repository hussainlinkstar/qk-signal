# Skill: Link Authority Auditor

## Purpose
Evaluate the internal and external link architecture of a website to assess link equity distribution, authority signals, backlink profile health, and linking practices that influence search visibility and domain trust. This skill identifies structural link issues that suppress rankings and opportunities to strengthen the site's authority through strategic linking.

## Signal Checklist

### Priority 1, Critical Signals

- **Internal Link Architecture**: Assess the site's link topology, hub-and-spoke structure connecting pillar pages to cluster content, siloed content within topical groups. Detect orphan pages (pages with no internal links pointing to them) and measure click depth from the homepage to important pages. Check for breadcrumb navigation providing hierarchical context. Good = all important pages reachable within <=3 clicks from the homepage, clear topical hubs linking to related content, breadcrumb navigation implemented with BreadcrumbList schema, logical site architecture reflecting topic hierarchy. Bad = orphan pages with zero internal links, critical commercial pages buried 5+ clicks deep, flat structure with no topical clustering, broken breadcrumb trails or missing breadcrumbs entirely.

- **Broken Link Detection**: Identify internal 404 errors (links pointing to pages that no longer exist) and broken external outbound links. Both waste link equity and degrade user experience. Internal broken links are more damaging because they represent equity loss within the site's own link graph. Good = zero internal 404s, external outbound links verified and functional, 301 redirects properly implemented for moved content. Bad = multiple internal links pointing to deleted pages without redirects, outbound links to domains that no longer exist, soft 404s (pages that load but show "not found" content without a 404 status code), redirect chains exceeding 3 hops.

- **Link Equity Flow**: Evaluate whether high-value pages (commercial pages, pillar content, conversion pages) receive proportional internal link equity. Check homepage link budget distribution, the homepage typically carries the most authority and its outbound links determine where that equity flows. Good = strategic internal linking that reinforces the site's priority pages, link equity flows from high-authority pages to pages that need ranking support, contextual links from relevant content direct equity where it matters. Bad = link equity diluted across hundreds of low-value pages (tag pages, archive pages, utility pages), important commercial pages receiving fewer internal links than blog tags or author archives, homepage linking to every page equally without prioritization.

- **Toxic Backlink Indicators**: Scan for signals of manipulative link building, links from private blog networks (PBNs), link schemes, suspected paid links without proper disclosure, large volumes of irrelevant foreign-language links, links from hacked sites or malware-infected domains. Good = clean backlink profile with no evidence of artificial link acquisition, links earned through content quality and outreach. Bad = clusters of links from low-quality directories, link farms, or sites with no topical relevance; sudden spikes in backlink acquisition suggesting purchased campaigns; links from domains with spammy TLDs (.xyz, .top, .click) in disproportionate volumes; identical anchor text from multiple unrelated domains.

### Priority 2, High-Impact Signals

- **Anchor Text Quality**: Evaluate the descriptive quality and diversity of anchor text across internal and external links. Anchor text tells search engines and users what the linked page is about. Assess both internal anchor text (within the site's control) and external backlink anchor text (earned from other sites). Good = descriptive, contextually relevant internal anchors ("complete guide to mortgage rates" vs "click here"), natural distribution of external anchor text across branded, URL, generic, and keyword-rich variants. Bad = generic anchors ("read more", "click here", "learn more") dominating internal links; over-optimization where >30% of external backlinks use the exact same keyword-rich phrase (signals manipulation); exact-match anchor text from obviously unrelated sites.

- **External Link Profile Signals**: Assess the diversity and quality of the site's inbound backlink profile, domain authority distribution across referring domains, follow vs nofollow ratio, total referring domain count (more important than total link count), and link velocity (rate of new link acquisition over time). Good = diverse referring domains across multiple authority tiers (some high-DA, many mid-DA, natural tail of low-DA), natural follow/nofollow mix (~70-80% follow is typical), steady link growth correlating with content publication. Bad = backlinks concentrated from a handful of domains (even if high-DA, lack of diversity is a risk), 100% follow links (unnatural, real profiles always include some nofollow), erratic link velocity with suspicious spikes followed by plateaus.

- **Outbound Link Quality**: Evaluate where the site links out to, are outbound links pointing to authoritative, topically relevant sources? Outbound links signal the neighborhood the site associates with and can affect trustworthiness. Good = editorial outbound links to reputable sources that enhance content credibility (government sites, academic institutions, recognized industry authorities, peer-reviewed research), outbound links used to cite claims and support arguments. Bad = links to low-quality or spammy sites, excessive affiliate links without rel="sponsored", broken outbound links left unrepaired for extended periods, outbound links to known penalized domains.

- **Nofollow/Sponsored/UGC Attribute Usage**: Verify proper use of link relationship attributes: `rel="nofollow"` for untrusted links, `rel="sponsored"` for paid/promotional links, `rel="ugc"` for user-generated content links. Google treats these as hints, but proper usage demonstrates editorial care. Good = paid/sponsored links properly marked with `rel="sponsored"`, user-generated content links (comments, forum posts) with `rel="ugc"`, affiliate links with appropriate nofollow/sponsored tags. Bad = paid links passing equity without any rel attribute (Google guidelines violation), blanket nofollow on ALL outbound links (wastes editorial link value from legitimate citations), no rel attributes on user-submitted links in comments or forums.

### Priority 3, Supporting Signals

- **Link Placement Value**: Assess where links appear within the page layout and content. In-content editorial links (within paragraph text) carry the most weight because they appear contextually relevant and are more likely clicked by users. Sidebar links, footer links, and navigation links carry progressively less weight. Good = important internal links placed naturally within body content, contextually relevant to the surrounding text, editorial links appearing where a reader would naturally want more information. Bad = critical internal links appearing only in footer or sidebar menus, no contextual in-content linking between related pages, all links concentrated in navigation elements with zero body-content links.

- **Natural Link Profile Characteristics**: Evaluate whether the overall backlink profile exhibits organic growth patterns. Natural profiles have diverse anchor text distribution, variety of link types (dofollow, nofollow, redirect-based), and gradual accumulation over time correlating with content publishing and marketing activities. Good = anchor text distribution follows a natural curve (branded terms > naked URLs > generic phrases > keyword-rich phrases), link types are varied, growth rate is steady and proportional to content output and brand visibility. Bad = unnatural anchor text concentration where 90%+ of links use exact-match keyword anchors, all links acquired within a narrow timeframe, link profile doesn't correlate with any visible content marketing or PR activity.

- **Reciprocal Linking Patterns**: Detect excessive reciprocal links (Site A links to Site B, Site B links back to Site A) suggesting organized link exchange schemes. Some reciprocal linking is natural (business partners, industry peers citing each other, mutual references in collaborative content), but large-scale patterns suggest manipulation. Good = some reciprocal links exist naturally (partners, industry peers, co-authored research) but represent a small percentage (<10%) of the total backlink profile. Bad = large-scale reciprocal linking patterns visible across dozens of domains, dedicated "partners" or "links" pages designed specifically for link exchanges, 1:1 link swap agreements visible across multiple sites.

- **Competitor Link Gap Analysis**: Identify authoritative domains that link to direct competitors but not to this site. These represent realistic link acquisition opportunities because the linking domain has demonstrated willingness to link to content in this niche. Good = awareness of link gaps with evidence of content or outreach strategies to close them, identification of the most impactful gap domains. Bad = not an error if gaps exist, flag as an opportunity, not a deficiency; competitor link gaps are normal and expected, especially for newer or smaller sites.

- **Redirect Chain Audit**: Check for redirect chains (URL A → URL B → URL C → final destination) that waste link equity at each hop. Each redirect loses a small amount of equity and adds latency. Good = direct 301 redirects from old URLs to final destinations, no chains exceeding 2 hops, all redirects using 301 (permanent) not 302 (temporary) for permanently moved content. Bad = redirect chains with 3+ hops, 302 redirects used for permanent moves (equity may not pass), redirect loops, mixed HTTP/HTTPS redirects creating unnecessary chains.

## Evaluation Framework

- **Critical**: Multiple orphan pages containing important commercial or informational content with no internal links pointing to them; toxic backlink patterns indicating active link schemes, PBN usage, or large-scale paid links without disclosure; widespread internal 404 errors (>10 broken internal links) indicating systematic link rot; important commercial pages completely unreachable beyond 4+ clicks with no direct internal links from relevant pages.

- **High**: Anchor text over-optimization where >30% of external backlinks use the exact same keyword-rich phrase (algorithmic manipulation signal); link equity flowing primarily to low-value pages (tag archives, author pages) while commercial and pillar pages are underlinked; outbound links to known spammy, malware-infected, or penalized domains; missing rel="sponsored" attributes on clearly paid or promotional links; redirect chains of 4+ hops on pages with significant backlink equity.

- **Medium**: Generic anchor text ("click here", "read more") on >50% of internal links, reducing the semantic value of internal linking; uneven internal link distribution without clear strategic intent; moderate broken link count (5-10 internal 404s); nofollow applied too broadly to all outbound links regardless of editorial value; backlink profile with limited domain diversity (<20 unique referring domains for an established site); 302 redirects used for permanent URL changes.

- **Low**: Minor anchor text improvements possible on secondary pages; footer-only internal links to secondary informational pages; small competitor link gaps representing nice-to-have opportunities; slightly suboptimal link placement (sidebar links where in-content would be stronger); missing breadcrumb navigation on deep pages; reciprocal links representing <5% of profile (natural levels).

## Common False Positives (DO NOT flag these)

- **Low external link count for new sites**: Domain authority and backlink volume build over time through content quality and marketing efforts. A new site (<1 year old) with fewer than 50 referring domains is normal, not a critical issue. Evaluate link profile quality relative to the site's age, niche competitiveness, and content volume. Flag as an opportunity for link building strategy, not as a deficiency.

- **High nofollow ratio on UGC-heavy sites**: Forums, review platforms, Q&A sites, community-driven platforms, and comment-heavy blogs should nofollow all user-submitted links. A 90%+ nofollow outbound ratio is correct and expected on these site types, it demonstrates proper editorial control over user-generated content.

- **Footer/sidebar links appearing across all pages**: Sitewide navigation links in the footer and sidebar are standard web design patterns, not link manipulation. These include links to main categories, legal pages, contact information, and social profiles. Only flag if unrelated external links (especially to commercial third-party sites) appear sitewide, which may indicate paid link injection or compromised templates.

- **Few internal links on the homepage**: The homepage should link to main sections, key categories, and featured content, not to every individual page on the site. A focused homepage linking structure (10-30 primary links) is intentional information architecture. Only flag if key commercial sections or main category pages are completely absent from homepage navigation and not linked anywhere within 2 clicks.

- **No outbound links on landing pages**: Conversion-focused landing pages (PPC landing pages, sales pages, signup pages) intentionally minimize exit opportunities to maximize conversion rates. Absence of outbound links on these pages is a deliberate UX/conversion optimization decision, not a linking deficiency. Do not penalize focused conversion architecture.

- **Branded anchor text dominance in backlinks**: A high percentage (40-60%) of branded anchors (company name, domain name, brand variations) in the external backlink profile is a healthy, natural signal. This is the most common anchor type in organic profiles. Do not flag branded anchor dominance as "missing keyword optimization", the opposite (low branded percentage) would be more concerning.

- **Dofollow links to trusted sources**: Editorial outbound links to authoritative sources (Wikipedia, government sites, academic journals, recognized industry publications) should be dofollow. Nofollowing these links wastes editorial signal. Do not flag dofollow outbound links to clearly reputable sources as missing nofollow attributes.

## Page-Type Awareness

- **Homepage**: Evaluate as the primary link equity distributor, the homepage typically receives the most external backlinks and its internal link structure determines how that authority flows to the rest of the site. Check that it links to all major sections, key commercial pages, and pillar content. Assess external backlink concentration, the homepage typically receives 30-60% of all referring domains. Verify BreadcrumbList schema is implemented.

- **Product/Service Pages**: These should be among the most internally linked pages on the site, receiving contextual links from blog posts, category pages, comparison pages, and related product cross-links. Verify they receive in-content links (not just navigation links) from topically relevant pages. Check for proper cross-linking between related products/services. Outbound links may be intentionally minimal on conversion-focused product pages.

- **Blog/Article Pages**: Evaluate bidirectional internal linking, articles should link to relevant pillar pages, category hubs, and related articles. These pages are typically the primary link earners, attracting natural backlinks through content quality. Check that editorial outbound links to authoritative sources enhance content credibility. Verify that blog posts link to the commercial pages they support (product mentions, service references).

- **Category/Hub Pages**: Act as topical authority nodes in the site architecture, verify they link comprehensively to all child/cluster pages and receive links back from them. Assess whether the hub-spoke topology is complete (no child pages missing from the hub). These pages should consolidate link equity for their topic cluster and are often high-value ranking targets for competitive head terms.

- **Contact/About Pages**: Typically receive sitewide footer links (normal and expected). External backlinks to these pages are uncommon and not required for authority. Verify they link to relevant trust signals (certifications, memberships, press mentions, team profiles). These pages rarely need link-building attention.

- **Legal Pages**: Minimal link equity considerations. Sitewide footer links are standard and sufficient. Do not flag for low internal or external link counts. Only verify that these pages are accessible (not orphaned) and not accidentally blocked by robots directives. Legal pages should not receive strategic internal linking attention at the expense of commercial pages.

- **Resource/Tools Pages**: High link-earning potential, linkable assets (calculators, templates, datasets, tools, original research) are among the most effective natural link magnets. Evaluate whether these pages are prominently internally linked from relevant content and whether they are positioned to attract natural backlinks. Check whether the site promotes these assets through content marketing to maximize link acquisition potential.

## Scoring Guidance

When scoring link authority, distinguish between issues the site can fix immediately (internal linking, broken links, rel attributes) and issues that require long-term strategy (backlink profile, domain authority, competitor link gaps):

- **Quick Wins (flag as actionable)**: Broken internal links, orphan pages, missing breadcrumbs, generic anchor text on internal links, missing rel attributes on paid links, redirect chains. These can be fixed in a single deployment cycle.

- **Strategic Issues (flag as recommendations)**: Thin backlink profile, low domain diversity, competitor link gaps, underlinked commercial pages. These require content strategy, outreach campaigns, and time to address.

- **Monitoring Items (flag as informational)**: Link velocity trends, anchor text distribution shifts, new toxic backlinks detected. These aren't actionable in a single audit but should be tracked over time.

- **Risk Indicators (flag with urgency level)**: Toxic backlinks, link scheme patterns, over-optimized anchor text. These may require immediate disavow action or link removal outreach to prevent algorithmic penalties.

## Interaction with Other Skills

- **SEO On-Page Auditor**: Internal linking signals overlap, the on-page auditor evaluates internal links for anchor text and orphan page detection, while this skill evaluates the strategic equity flow and architectural topology. Coordinate to avoid flagging the same internal link issue twice. This skill owns the structural/authority perspective; the on-page auditor owns the per-page optimization perspective.

- **Content Quality Evaluator**: Content quality drives natural link acquisition. When this skill identifies a thin backlink profile, the root cause may be low content quality rather than poor outreach. Cross-reference with content quality findings, if the site's content scores low on information density, topical depth, or E-E-A-T, link-building recommendations should be secondary to content improvement.

- **Technical SEO Auditor**: Redirect chains, broken links, and crawlability issues overlap. The technical SEO auditor evaluates these from a crawl-efficiency and indexability perspective; this skill evaluates them from a link-equity-preservation perspective. Both perspectives are valid, ensure findings reference the link equity impact specifically.
