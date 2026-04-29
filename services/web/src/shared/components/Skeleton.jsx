/**
 * Skeleton placeholders for content-shaped loading states.
 *
 * Spinners say "I'm doing something". Skeletons say "the answer is
 * about to appear right here, in this layout". For dashboard /
 * case-detail style pages with a known structure, that's a notably
 * better perceived-performance signal — citizens see the page
 * outline immediately and don't experience a jarring layout shift
 * when the data lands.
 *
 * Three primitives:
 *   <Skeleton />                  — single rectangle (defaults to a
 *                                   line of text height)
 *   <SkeletonRows rows={N} />     — stack of N text-row rectangles
 *   <SkeletonCard />              — header line + 3 body rows, sized
 *                                   like the .detail-section blocks
 *                                   used elsewhere on dashboard.css
 *
 * All three use the .skeleton CSS class for the shimmer animation.
 */

export function Skeleton({ width = '100%', height = '1rem', radius = '4px', style }) {
  return (
    <div
      className="skeleton"
      aria-hidden="true"
      style={{ width, height, borderRadius: radius, ...style }}
    />
  );
}

export function SkeletonRows({ rows = 3, gap = '0.5rem' }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap }}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton
          key={i}
          // Vary widths a bit so the stack doesn't look like a barcode
          width={`${85 - (i % 3) * 12}%`}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ rows = 3 }) {
  return (
    <div
      className="skeleton-card"
      role="status"
      aria-label="Loading"
    >
      <Skeleton width="40%" height="1.2rem" />
      <div style={{ height: '0.75rem' }} />
      <SkeletonRows rows={rows} />
    </div>
  );
}
