class FunctionRegister:

    def __init__(self):
        self.functions = {}

    def register(self,func):
        if func.__name__ in self.functions:
            raise ValueError(f"{func.__name__} already present in registry")
        self.functions[func.__name__] = func
        return func

    def retrieve(self, name):
        if name in self.functions:
            res = self.functions[name]
        else:
            raise ValueError(f"given name is not present in our registry")

        return res

    def unregister(self, name):
        if name in self.functions:
            del self.functions[name]
        else:
            raise ValueError("Given name is not present in our registry")

    def enlist(self):
        return list(self.functions.keys())



# registry = FunctionRegister()

# def add(a, b):
#     return a + b

# def multiply(a, b):
#     return a * b

# registry.register(add)
# registry.register(multiply)

# fn = registry.retrieve("add")
# print(fn(3, 4))  # 7
# # registry.register(add)  # Should raise ValueError

# registry.unregister("multiply")
# print(registry.functions)