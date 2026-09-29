import ast
import json

class RouteVisitor(ast.NodeVisitor):
    def __init__(self):
        self.routes = []

    def visit_FunctionDef(self, node):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if dec.func.value.id == 'app' and dec.func.attr in ['route', 'get', 'post', 'put', 'delete']:
                    route_path = dec.args[0].value if dec.args else "UNKNOWN"
                    method = dec.func.attr.upper() if dec.func.attr != 'route' else "GET" # Simplified
                    docstring = ast.get_docstring(node)
                    calls = []
                    
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                            if hasattr(child.func.value, 'id'):
                                calls.append(f"{child.func.value.id}.{child.func.attr}")
                            
                    self.routes.append({
                        "path": route_path,
                        "method": method,
                        "function": node.name,
                        "docstring": docstring,
                        "calls": list(set(calls))
                    })
        self.generic_visit(node)

with open('app.py', 'r', encoding='utf-8') as f:
    tree = ast.parse(f.read())
    
visitor = RouteVisitor()
visitor.visit(tree)

with open('routes.json', 'w', encoding='utf-8') as f:
    json.dump(visitor.routes, f)
