from greet import greet

def test_greet():
    assert greet("World") == "Hello, World!"
    assert greet("Python") == "Hello, Python!"

test_greet()