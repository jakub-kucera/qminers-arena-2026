"""Fold a bot module into one top-level BaseStrategy subclass: its constants, functions and helper classes
become members of that class; references to them inside function bodies become `ArenaBot.<name>`."""
import ast, sys
from pathlib import Path

src = Path(sys.argv[1]).read_text()
tree = ast.parse(src)
imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
rest = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom)) and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
main = next(n for n in rest if isinstance(n, ast.ClassDef) and n.name == "ArenaBot")
members = [n for n in rest if n is not main]
names = set()
for n in members + main.body:
    if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
        names.add(n.name)
    elif isinstance(n, ast.Assign):
        names.update(t.id for t in n.targets if isinstance(t, ast.Name))
    elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
        names.add(n.target.id)
main_methods = {n.name for n in main.body if isinstance(n, ast.FunctionDef)}
names -= main_methods  # ArenaBot's own methods are reached through self already

class Qualify(ast.NodeTransformer):
    """Inside function bodies, a module-level name becomes ArenaBot.<name> (looked up when called)."""
    def __init__(self):
        self.local = [set()]
    def visit_FunctionDef(self, node):
        args = {a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}
        if node.args.vararg: args.add(node.args.vararg.arg)
        if node.args.kwarg: args.add(node.args.kwarg.arg)
        assigned = {t.id for t in ast.walk(node) if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)}
        self.local.append(args | assigned)
        node.body = [self.visit(b) for b in node.body]  # defaults and annotations are left as they are
        self.local.pop()
        return node
    def visit_Lambda(self, node):
        return node
    def visit_Name(self, node):
        if len(self.local) > 1 and isinstance(node.ctx, ast.Load) and node.id in names and node.id not in self.local[-1]:
            return ast.copy_location(ast.Attribute(value=ast.Name(id="ArenaBot", ctx=ast.Load()), attr=node.id, ctx=ast.Load()), node)
        return node

class Strip(ast.NodeTransformer):
    """Annotations do nothing at run time, but a nested class's method can't see the other nested classes they name."""
    def visit_arg(self, node):
        node.annotation = None
        return node
    def visit_FunctionDef(self, node):
        node.returns = None
        self.generic_visit(node)
        return node
    def visit_AnnAssign(self, node):
        if node.value is None:
            return None
        return ast.copy_location(ast.Assign(targets=[node.target], value=node.value), node)

tree = Strip().visit(tree)
rest = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom)) and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
main = next(n for n in rest if isinstance(n, ast.ClassDef) and n.name == "ArenaBot")
members = [n for n in rest if n is not main]
q = Qualify()
members = [q.visit(n) for n in members]
main.body = [q.visit(n) for n in main.body]
main.body = members + main.body
tree.body = imports + [main]
ast.fix_missing_locations(tree)
out = ast.unparse(tree)
Path(sys.argv[2]).write_text(out + "\n")
print("members folded:", len(members), "names qualified:", len(names))
