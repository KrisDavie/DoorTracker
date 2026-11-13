"""Layout solvers over blocks as rigid bodies. No knowledge of doors or the model."""

import math
import random
from collections import defaultdict
from dataclasses import dataclass

LINK_GAP = 46  # preferred door-to-door distance of a link
MIN_GAP = 14  # minimum block spacing during layout search
CONTACT_RANGE = 44  # stiff repulsion inside this distance
CONTACT_STRENGTH = 0.5
HARD_GAP = 4  # minimum spacing while settling
REPEL_RANGE = 60  # default repulsion reach (Spacing slider)
REPEL_STRENGTH = 0.12  # fraction of the shortfall corrected per step
LINK_PULL_MAX = 10  # stretch at which link pull stops growing linearly


@dataclass
class Damping:
    """Step damping of one body while settling. The caller keeps it between calls."""

    scale: float = 1.0  # fraction of each step taken
    dx: float = 0.0  # last step
    dy: float = 0.0


@dataclass
class Body:
    """One block as the solvers see it. Positions are of its origin."""

    rects: list  # rooms as (centre x, centre y, half width, half height), relative to the origin
    mobility: float  # 0 fixed .. 1 free
    weight: int  # room count
    damping: Damping
    group: object = None  # bodies sharing a group attract when grouping is on


@dataclass(frozen=True)
class Spring:
    """A link between two bodies, pulling its two ports together."""

    a: int  # body index
    ax: float  # port, relative to the body's origin
    ay: float
    b: int
    bx: float
    by: float
    facing_a: tuple = None  # unit vector the door faces; None for stairs, drops and warps
    facing_b: tuple = None


def enclosing_circle(points):
    """Smallest circle containing every point, as (x, y, radius)."""

    def from_two(a, b):
        return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, math.dist(a, b) / 2

    def from_three(a, b, c):
        d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        if abs(d) < 1e-9:
            return None
        ux = ((a[0] ** 2 + a[1] ** 2) * (b[1] - c[1]) + (b[0] ** 2 + b[1] ** 2) * (c[1] - a[1]) + (c[0] ** 2 + c[1] ** 2) * (a[1] - b[1])) / d
        uy = ((a[0] ** 2 + a[1] ** 2) * (c[0] - b[0]) + (b[0] ** 2 + b[1] ** 2) * (a[0] - c[0]) + (c[0] ** 2 + c[1] ** 2) * (b[0] - a[0])) / d
        return ux, uy, math.dist((ux, uy), a)

    def holds(circle, point):
        return circle is not None and math.dist(circle[:2], point) <= circle[2] + 1e-6

    # Incremental construction; fine for the few points per block
    points = list(dict.fromkeys(points))
    circle = None
    for i, p in enumerate(points):
        if holds(circle, p):
            continue
        circle = (p[0], p[1], 0.0)
        for j, q in enumerate(points[:i]):
            if holds(circle, q):
                continue
            circle = from_two(p, q)
            for r in points[:j]:
                if not holds(circle, r):
                    circle = from_three(p, q, r) or circle
    return circle


def link_offset(facing_a, facing_b, gap=LINK_GAP):
    """Where door b should sit relative to door a, given the directions they face; None if neither has one."""
    if facing_a is not None and facing_b is not None:
        return ((facing_a[0] - facing_b[0]) / 2 * gap, (facing_a[1] - facing_b[1]) / 2 * gap)
    if facing_a is not None:
        return (facing_a[0] * gap, facing_a[1] * gap)
    if facing_b is not None:
        return (-facing_b[0] * gap, -facing_b[1] * gap)
    return None


def relax(bodies, xs, ys, springs, *, iterations, spacing, leaf_pull, improve=False, cold=False, circles=False, grouped=False):
    """Force solver.

    Returns (xs, ys, total link length, mean movement per iteration).
    """
    # Where each spring wants port b relative to port a; None if neither door has a direction
    wants = [link_offset(spring.facing_a, spring.facing_b) for spring in springs]
    gap = LINK_GAP
    n = len(bodies)
    start_x, start_y = xs[:], ys[:]
    damping = [body.damping for body in bodies]
    rects = [body.rects for body in bodies]
    mobility = [body.mobility for body in bodies]
    centres = []
    extents = []
    for boxes in rects:
        centres.append((sum(b[0] for b in boxes) / len(boxes), sum(b[1] for b in boxes) / len(boxes)))
        extents.append(
            (
                min(b[0] - b[2] for b in boxes),
                max(b[0] + b[2] for b in boxes),
                min(b[1] - b[3] for b in boxes),
                max(b[1] + b[3] for b in boxes),
            )
        )

    # Bounding circles for a quick reject
    mid_x = [(e[0] + e[1]) / 2 for e in extents]
    mid_y = [(e[2] + e[3]) / 2 for e in extents]
    radius = [math.hypot(e[1] - e[0], e[3] - e[2]) / 2 for e in extents]

    incident = [[] for _ in range(n)]  # per body: indices of its springs
    for k, spring in enumerate(springs):
        incident[spring.a].append(k)
        incident[spring.b].append(k)

    groups = []
    if grouped:
        by_group = defaultdict(list)
        for i, body in enumerate(bodies):
            by_group[body.group].append(i)
        groups = [members for members in by_group.values() if len(members) > 1]

    margin_x = margin_y = HARD_GAP if cold else MIN_GAP
    reach = spacing
    far = max(reach, CONTACT_RANGE)

    if circles:
        circles = [
            enclosing_circle([(bx + sx * hw, by + sy * hh) for bx, by, hw, hh in boxes for sx in (-1, 1) for sy in (-1, 1)])
            for boxes in rects
        ]
    else:
        circles = []

    def repulsion():
        """Push apart blocks closer than the reach."""
        # Circle mode still uses wall-to-wall contact at close range
        near = CONTACT_RANGE if circles else far
        for a in range(n):
            ea = extents[a]
            for b in range(a + 1, n):
                ma, mb = mobility[a], mobility[b]
                if ma + mb == 0:
                    continue
                if not circles:
                    dx = xs[b] + mid_x[b] - xs[a] - mid_x[a]
                    dy = ys[b] + mid_y[b] - ys[a] - mid_y[a]
                    limit = radius[a] + radius[b] + near
                    if dx * dx + dy * dy > limit * limit:
                        continue
                # Split the move by inverse mass (room count)
                ease_a, ease_b = ma / weight[a], mb / weight[b]
                share_a, share_b = ease_a / (ease_a + ease_b), ease_b / (ease_a + ease_b)
                if circles:
                    ca, cb = circles[a], circles[b]
                    cx = xs[b] + cb[0] - xs[a] - ca[0]
                    cy = ys[b] + cb[1] - ys[a] - ca[1]
                    apart = math.hypot(cx, cy)
                    gap = apart - ca[2] - cb[2]
                    if gap < reach:
                        if apart < 1e-6:
                            cx, cy, apart = 1.0, 0.0, 1.0
                        push = REPEL_STRENGTH * (reach - max(0.0, gap))
                        xs[a] -= cx / apart * push * share_a
                        ys[a] -= cy / apart * push * share_a
                        xs[b] += cx / apart * push * share_b
                        ys[b] += cy / apart * push * share_b
                eb = extents[b]
                sx, sy = xs[b] - xs[a], ys[b] - ys[a]
                if (
                    sx + eb[0] - near >= ea[1]
                    or sx + eb[1] + near <= ea[0]
                    or sy + eb[2] - near >= ea[3]
                    or sy + eb[3] + near <= ea[2]
                ):
                    continue
                # Wall-to-wall gap of the closest pair of rooms
                nearest = near
                ux = uy = 0.0
                for ax, ay, ahw, ahh in rects[a]:
                    for bx, by, bhw, bhh in rects[b]:
                        dx = sx + bx - ax
                        dy = sy + by - ay
                        gap_x = max(0.0, abs(dx) - ahw - bhw)
                        gap_y = max(0.0, abs(dy) - ahh - bhh)
                        distance = math.hypot(gap_x, gap_y)
                        if distance < nearest:
                            nearest = distance
                            if distance > 1e-6:
                                ux, uy = (gap_x if dx >= 0 else -gap_x), (gap_y if dy >= 0 else -gap_y)
                            else:
                                ux, uy = dx, dy
                if nearest >= near:
                    continue
                norm = math.hypot(ux, uy) or 1.0
                # Applied per pair (Gauss-Seidel), which avoids overshoot in crowds
                push = CONTACT_STRENGTH * max(0.0, CONTACT_RANGE - nearest)
                if not circles:
                    push += REPEL_STRENGTH * max(0.0, reach - nearest)
                xs[a] -= ux / norm * push * share_a
                ys[a] -= uy / norm * push * share_a
                xs[b] += ux / norm * push * share_b
                ys[b] += uy / norm * push * share_b

    def overlap(a, b):
        """Shortest axis-aligned move of block b that clears block a; (0, 0) if clear."""
        ea, eb = extents[a], extents[b]
        sx, sy = xs[b] - xs[a], ys[b] - ys[a]
        if (
            sx + eb[0] - margin_x >= ea[1]
            or sx + eb[1] + margin_x <= ea[0]
            or sy + eb[2] - margin_y >= ea[3]
            or sy + eb[3] + margin_y <= ea[2]
        ):
            return 0.0, 0.0
        # One move that clears every room pair; per-pair pushes can cycle in a notch
        right = left = down = up = 0.0
        touching = False
        for ax, ay, ahw, ahh in rects[a]:
            for bx, by, bhw, bhh in rects[b]:
                dx = sx + bx - ax
                dy = sy + by - ay
                wsum = ahw + bhw + margin_x
                hsum = ahh + bhh + margin_y
                in_row = -hsum < dy < hsum
                in_column = -wsum < dx < wsum
                if not in_row and not in_column:
                    continue
                if in_row:
                    right = max(right, wsum - dx)
                    left = max(left, wsum + dx)
                if in_column:
                    down = max(down, hsum - dy)
                    up = max(up, hsum + dy)
                if in_row and in_column:
                    touching = True
        if not touching:
            return 0.0, 0.0
        shortest = min(right, left, down, up)
        if shortest == right:
            return right, 0.0
        if shortest == left:
            return -left, 0.0
        if shortest == down:
            return 0.0, down
        return 0.0, -up

    def separate(strength):
        moved = False
        for a in range(n):
            for b in range(a + 1, n):
                ma, mb = mobility[a], mobility[b]
                if ma + mb == 0:
                    continue
                dx = xs[b] + mid_x[b] - xs[a] - mid_x[a]
                dy = ys[b] + mid_y[b] - ys[a] - mid_y[a]
                limit = radius[a] + radius[b] + margin_x
                if dx * dx + dy * dy > limit * limit:
                    continue
                push_x, push_y = overlap(a, b)
                if not push_x and not push_y:
                    continue
                moved = True
                # Split the move by inverse mass (room count)
                ease_a, ease_b = ma / weight[a], mb / weight[b]
                share_a, share_b = ease_a / (ease_a + ease_b), ease_b / (ease_a + ease_b)
                xs[a] -= push_x * strength * share_a
                xs[b] += push_x * strength * share_b
                ys[a] -= push_y * strength * share_a
                ys[b] += push_y * strength * share_b
        return moved

    def cost(i):
        total = 0.0
        for k in incident[i]:
            s, want = springs[k], wants[k]
            dx = xs[s.b] + s.bx - xs[s.a] - s.ax
            dy = ys[s.b] + s.by - ys[s.a] - s.ay
            if want is not None:
                dx -= want[0]
                dy -= want[1]
            total += math.hypot(dx, dy)
        return total

    degree = [len(x) for x in incident]
    # Satellite pull: links of a block connected to only one other block pull leaf_pull**3 harder
    neighbours = [set() for _ in range(n)]
    for spring in springs:
        neighbours[spring.a].add(spring.b)
        neighbours[spring.b].add(spring.a)
    pull_limit = [
        LINK_PULL_MAX * (leaf_pull**3 if len(neighbours[spring.a]) == 1 or len(neighbours[spring.b]) == 1 else 1.0)
        for spring in springs
    ]
    weight = [body.weight for body in bodies]
    total_weight = sum(weight)

    for it in range(iterations):
        cooling = 1 - it / iterations
        # Cold: no large moves
        temperature = 10 if cold else 80 * cooling + 4
        if cold:
            prev_x, prev_y = xs[:], ys[:]
        tx = [0.0] * n
        ty = [0.0] * n
        for k, spring in enumerate(springs):
            ia, ib, want = spring.a, spring.b, wants[k]
            pax, pay = xs[ia] + spring.ax, ys[ia] + spring.ay
            pbx, pby = xs[ib] + spring.bx, ys[ib] + spring.by
            if want is None:
                # No direction: target one card apart
                dx, dy = pbx - pax, pby - pay
                dist = math.hypot(dx, dy) or 0.01
                vx, vy = dx / dist * gap * 2, dy / dist * gap * 2
            else:
                vx, vy = want
            ex, ey = pax + vx - pbx, pay + vy - pby
            if cold:
                stretch = math.hypot(ex, ey)
                if stretch > pull_limit[k]:
                    # Beyond LINK_PULL_MAX the pull grows as sqrt(stretch)
                    pull = math.sqrt(stretch * pull_limit[k])
                    ex, ey = ex / stretch * pull, ey / stretch * pull
            # Equal and opposite, split by inverse mass; asymmetric pulls make the map drift
            share = 2 / max(degree[ia], degree[ib]) / (weight[ia] + weight[ib])
            tx[ib] += ex * share * weight[ia]
            ty[ib] += ey * share * weight[ia]
            tx[ia] -= ex * share * weight[ib]
            ty[ia] -= ey * share * weight[ib]

        # No centring force; "Group by original dungeon" pulls towards each dungeon's centroid
        gx = [None] * n
        gy = [None] * n
        for members in groups:
            mx = sum(xs[i] + centres[i][0] for i in members) / len(members)
            my = sum(ys[i] + centres[i][1] for i in members) / len(members)
            for i in members:
                gx[i], gy[i] = mx, my

        moves = []
        fastest = 0.0
        for i in range(n):
            if mobility[i] == 0:
                moves.append((0.0, 0.0))
                continue
            dx = dy = 0.0
            if gx[i] is not None:
                dx = (gx[i] - xs[i] - centres[i][0]) * 0.25
                dy = (gy[i] - ys[i] - centres[i][1]) * 0.25
            dx += tx[i] * 0.45
            dy += ty[i] * 0.45
            dx *= mobility[i]
            dy *= mobility[i]
            moves.append((dx, dy))
            fastest = max(fastest, math.hypot(dx, dy))
        # Cold: scale all moves by one factor; per-block caps break momentum balance and cause drift
        together = min(1.0, temperature / fastest) if cold and fastest else 1.0
        for i, (dx, dy) in enumerate(moves):
            step = math.hypot(dx, dy)
            if cold:
                dx, dy = dx * together, dy * together
            elif step > temperature:
                dx, dy = dx / step * temperature, dy / step * temperature
            xs[i] += dx
            ys[i] += dy
        repulsion()
        separate(1.0 if cold else 0.3 + 0.5 * (1 - cooling))
        if cold:
            # Half steps stop two blocks swapping places. Adaptive damping: halve a block's
            # step scale when it reverses direction, grow it while it keeps going.
            for i in range(n):
                dx = (xs[i] - prev_x[i]) / 2
                dy = (ys[i] - prev_y[i]) / 2
                state = damping[i]
                if dx * state.dx + dy * state.dy < 0:
                    state.scale = max(0.02, state.scale * 0.5)
                else:
                    state.scale = min(1.0, state.scale * 1.15)
                state.dx, state.dy = dx, dy
                xs[i] = prev_x[i] + dx * state.scale
                ys[i] = prev_y[i] + dy * state.scale

    for _ in range(80):
        if not separate(1.0):
            break

    if improve:
        # Relocation: try each block at the spot each of its links wants; keep it if total length drops
        def settle(i):
            for _ in range(40):
                clear = True
                for other in range(n):
                    if other == i:
                        continue
                    dx = xs[i] + mid_x[i] - xs[other] - mid_x[other]
                    dy = ys[i] + mid_y[i] - ys[other] - mid_y[other]
                    limit = radius[i] + radius[other] + margin_x
                    if dx * dx + dy * dy > limit * limit:
                        continue
                    push_x, push_y = overlap(other, i)
                    if push_x or push_y:
                        clear = False
                        xs[i] += push_x
                        ys[i] += push_y
                if clear:
                    return True
            return False

        movable = [i for i in range(n) if mobility[i] > 0 and degree[i]]
        for _ in range(5 if n <= 35 else 3):
            improved = False
            for i in sorted(movable, key=cost, reverse=True):
                before = cost(i)
                best = (before - 1, xs[i], ys[i])
                home = (xs[i], ys[i])
                spots = []
                sum_x = sum_y = 0.0
                for k in incident[i]:
                    s, want = springs[k], wants[k]
                    vx, vy = want if want is not None else (0.0, gap * 2)
                    if s.b == i and s.a != i:
                        spot = (xs[s.a] + s.ax + vx - s.bx, ys[s.a] + s.ay + vy - s.by)
                    elif s.a == i and s.b != i:
                        spot = (xs[s.b] + s.bx - vx - s.ax, ys[s.b] + s.by - vy - s.ay)
                    else:
                        continue
                    spots.append(spot)
                    sum_x += spot[0]
                    sum_y += spot[1]
                if not spots:
                    continue
                spots.append((sum_x / len(spots), sum_y / len(spots)))
                for spot_x, spot_y in spots:
                    xs[i], ys[i] = spot_x, spot_y
                    if settle(i):
                        value = cost(i)
                        if value < best[0]:
                            best = (value, xs[i], ys[i])
                xs[i], ys[i] = best[1], best[2]
                if (xs[i], ys[i]) != home:
                    improved = True
            if not improved:
                break

    if cold and iterations and all(mobility):
        # Cancel net drift
        shift_x = sum((xs[i] - start_x[i]) * weight[i] for i in range(n)) / total_weight
        shift_y = sum((ys[i] - start_y[i]) * weight[i] for i in range(n)) / total_weight
        xs = [x - shift_x for x in xs]
        ys = [y - shift_y for y in ys]
    moved = max((math.hypot(xs[i] - start_x[i], ys[i] - start_y[i]) for i in range(n)), default=0.0)
    return xs, ys, sum(cost(i) for i in range(n)) / 2, moved / max(1, iterations)



def stress(boxes, movable, xs, ys, springs, *, spacing):
    """Place blocks by stress majorization (Gansner, Koren and North 2004).

    Ideal distance between two blocks is the shortest path through links. Directly linked blocks
    also get a target offset from their door directions. Does not resolve overlaps.

    boxes: bounding box of each block as (left, top, right, bottom) relative to its origin.
    Returns (xs, ys) of the origins.
    """
    n = len(boxes)
    gap = LINK_GAP + spacing * 0.5
    centre = [((left + right) / 2, (top + bottom) / 2) for left, top, right, bottom in boxes]
    half = [((right - left) / 2, (bottom - top) / 2) for left, top, right, bottom in boxes]
    size = [(w + h) / 2 for w, h in half]

    wants = {}  # (i, j), i < j -> target centre offsets, one per link
    loose = {}  # (i, j) linked without a direction (stairs, drops, warps)
    ends = []
    for s in springs:
        if s.a > s.b:
            s = Spring(s.b, s.bx, s.by, s.a, s.ax, s.ay, s.facing_b, s.facing_a)
        i, j, da, db = s.a, s.b, s.facing_a, s.facing_b
        port = [(s.ax - centre[i][0], s.ay - centre[i][1]), (s.bx - centre[j][0], s.by - centre[j][1])]
        ends.append((i, j, port[0], port[1]))
        nx = (da[0] if da else 0) - (db[0] if db else 0)
        ny = (da[1] if da else 0) - (db[1] if db else 0)
        length = math.hypot(nx, ny)
        if length < 0.5:
            loose[(i, j)] = True
            continue
        nx, ny = nx / length, ny / length
        wants.setdefault((i, j), []).append((port[0][0] + nx * gap - port[1][0], port[0][1] + ny * gap - port[1][1]))
    target = {}
    for (i, j), vectors in wants.items():
        tx, ty = sum(v[0] for v in vectors) / len(vectors), sum(v[1] for v in vectors) / len(vectors)
        # Opposing links can average to ~0: enforce a minimum
        least = size[i] + size[j] + gap * 0.5
        length = math.hypot(tx, ty)
        if length < least:
            tx, ty = (tx / length * least, ty / length * least) if length > 1 else (least, 0.0)
        target[(i, j)] = (tx, ty)
        target[(j, i)] = (-tx, -ty)

    # All-pairs shortest paths (Floyd-Warshall)
    far = float("inf")
    dist = [[far] * n for _ in range(n)]
    for i in range(n):
        dist[i][i] = 0.0
    for (i, j), (tx, ty) in target.items():
        dist[i][j] = min(dist[i][j], math.hypot(tx, ty))
    for i, j in loose:
        if (i, j) not in target:
            dist[i][j] = dist[j][i] = min(dist[i][j], size[i] + size[j] + gap)
    for k in range(n):
        row_k = dist[k]
        for i in range(n):
            through = dist[i][k]
            if through == far:
                continue
            row_i = dist[i]
            for j in range(n):
                if through + row_k[j] < row_i[j]:
                    row_i[j] = through + row_k[j]
    group = list(range(n))
    for i in range(n):
        for j in range(i):
            if dist[i][j] < far:
                group[i] = group[j]
                break
    pairs = [[] for _ in range(n)]  # per block: (other, weight, ideal distance, target offset or None)
    for i in range(n):
        for j in range(n):
            if i == j or dist[i][j] == far:
                continue
            want = target.get((i, j))
            ideal = max(dist[i][j], size[i] + size[j] + gap * 0.5)
            # Direct links weigh 3x
            pairs[i].append((j, (3.0 if want else 1.0) / (ideal * ideal), ideal, want))

    def crossings(xs, ys):
        lines = [(xs[i] + pa[0], ys[i] + pa[1], xs[j] + pb[0], ys[j] + pb[1], i, j) for i, j, pa, pb in ends]
        count = 0
        for p, (ax, ay, bx, by, ai, aj) in enumerate(lines):
            for cx, cy, dx, dy, ci, cj in lines[p + 1 :]:
                if ai in (ci, cj) or aj in (ci, cj):
                    continue
                d1 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
                d2 = (bx - ax) * (dy - ay) - (by - ay) * (dx - ax)
                d3 = (dx - cx) * (ay - cy) - (dy - cy) * (ax - cx)
                d4 = (dx - cx) * (by - cy) - (dy - cy) * (bx - cx)
                if d1 * d2 < 0 and d3 * d4 < 0:
                    count += 1
        return count

    def solve(xs, ys):
        for sweep in range(200):
            moved = 0.0
            for i in range(n):
                if not movable[i] or not pairs[i]:
                    continue
                x, y = xs[i], ys[i]
                sx = sy = sw = 0.0
                for j, weight, ideal, want in pairs[i]:
                    if want:
                        sx += weight * (xs[j] - want[0])
                        sy += weight * (ys[j] - want[1])
                    else:
                        dx, dy = x - xs[j], y - ys[j]
                        apart = math.hypot(dx, dy)
                        if apart < 1e-6:
                            dx, dy, apart = 1.0, 0.0, 1.0
                        sx += weight * (xs[j] + ideal * dx / apart)
                        sy += weight * (ys[j] + ideal * dy / apart)
                    sw += weight
                xs[i], ys[i] = sx / sw, sy / sw
                moved = max(moved, abs(xs[i] - x), abs(ys[i] - y))
            if moved < 0.3:
                break
        stress = 0.0
        for i in range(n):
            for j, weight, ideal, want in pairs[i]:
                if want:
                    stress += weight * ((xs[j] - xs[i] - want[0]) ** 2 + (ys[j] - ys[i] - want[1]) ** 2)
                else:
                    stress += weight * (math.hypot(xs[i] - xs[j], ys[i] - ys[j]) - ideal) ** 2
        return stress

    start_x = [xs[i] + centre[i][0] for i in range(n)]
    start_y = [ys[i] + centre[i][1] for i in range(n)]
    rng = random.Random(n * 1000 + len(springs))
    spread = (sum(size) / max(n, 1) * 2 + gap) * math.sqrt(n)
    best = None
    for attempt in range(8 if n <= 40 else 5 if n <= 80 else 3):
        xs, ys = start_x[:], start_y[:]
        if attempt:
            for i in range(n):
                if movable[i]:
                    xs[i], ys[i] = rng.uniform(-spread, spread), rng.uniform(-spread, spread)
        stress = solve(xs, ys)
        score = (crossings(xs, ys), stress)
        if best is None or score < best[0]:
            best = (score, xs, ys)
    xs, ys = best[1], best[2]

    # Pack disconnected components in rows
    groups = {}
    for i in range(n):
        groups.setdefault(group[i], []).append(i)
    free = [g for g in groups.values() if all(movable[i] for i in g)]
    held = [i for g in groups.values() if g not in free for i in g]
    free.sort(key=lambda g: -len(g))
    boxes = []
    for g in free:
        boxes.append(
            (
                min(xs[i] - half[i][0] for i in g),
                min(ys[i] - half[i][1] for i in g),
                max(xs[i] + half[i][0] for i in g),
                max(ys[i] + half[i][1] for i in g),
            )
        )
    if free:
        area = sum((b[2] - b[0] + gap) * (b[3] - b[1] + gap) for b in boxes)
        row_width = max(math.sqrt(area) * 1.5, boxes[0][2] - boxes[0][0])
        left = max((xs[i] + half[i][0] for i in held), default=0.0) + (gap * 2 if held else 0.0)
        top = min((ys[i] - half[i][1] for i in held), default=0.0)
        x, y, row_height = left, top, 0.0
        for g, box in zip(free, boxes):
            width, height = box[2] - box[0], box[3] - box[1]
            if x > left and x + width > left + row_width:
                x, y, row_height = left, y + row_height + gap * 2, 0.0
            for i in g:
                xs[i] += x - box[0]
                ys[i] += y - box[1]
            x += width + gap * 2
            row_height = max(row_height, height)

    return [xs[i] - centre[i][0] for i in range(n)], [ys[i] - centre[i][1] for i in range(n)]


def convex_hull(points):
    points = sorted(set(points))
    if len(points) <= 2:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]
