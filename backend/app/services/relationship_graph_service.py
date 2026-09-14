class RelationshipGraphService:
    @staticmethod
    def qualified_edges(edges: list[tuple[str, str, float]], minimum_score: float) -> list[tuple[str, str]]:
        return [(first, second) for first, second, score in edges if score >= minimum_score]

    @staticmethod
    def connected_components(nodes: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
        adjacency = {node: set() for node in nodes}
        for first, second in edges:
            adjacency.setdefault(first, set()).add(second)
            adjacency.setdefault(second, set()).add(first)
        visited: set[str] = set()
        groups: list[list[str]] = []
        for node in adjacency:
            if node in visited:
                continue
            stack, component = [node], []
            visited.add(node)
            while stack:
                current = stack.pop()
                component.append(current)
                for neighbor in adjacency[current] - visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
            groups.append(sorted(component))
        return groups

