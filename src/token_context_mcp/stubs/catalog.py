from __future__ import annotations

from token_context_mcp.models import ExternalStubRecord

CURATED_EXTERNAL_STUBS: list[tuple[str, str, str, str, str]] = [
    # (package, export_path, member_name, signature, doc_summary)
    # pydantic
    ("pydantic", "BaseModel", "model_dump", "(mode='python', include=None, exclude=None) -> dict", "Generate a dictionary representation of the model."),
    ("pydantic", "BaseModel", "model_dump_json", "(*, indent=None, include=None, exclude=None) -> str", "Generates a JSON representation of the model."),
    ("pydantic", "BaseModel", "model_validate", "(obj, *, strict=None, from_attributes=None, context=None)", "Validate a Python object against the model."),
    ("pydantic", "BaseModel", "model_validate_json", "(json_data, *, strict=None, context=None)", "Validate JSON data against the model."),
    ("pydantic", "BaseModel", "model_copy", "(*, update=None, deep=False)", "Create a copy of the model with optional field updates."),
    ("pydantic", "BaseModel", "dict", "(include=None, exclude=None, by_alias=False) -> dict", "Pydantic v1 compatible dictionary serialization."),
    ("pydantic", "BaseModel", "json", "(include=None, exclude=None, by_alias=False) -> str", "Pydantic v1 compatible JSON serialization."),
    ("pydantic", "BaseModel", "parse_obj", "(obj)", "Pydantic v1 compatible object validation."),
    ("pydantic", "BaseModel", "parse_raw", "(b, *, content_type=None)", "Pydantic v1 compatible raw data validation."),
    ("pydantic", "BaseModel", "copy", "(*, include=None, exclude=None, update=None, deep=False)", "Pydantic v1 compatible copy."),
    # unittest
    ("unittest", "TestCase", "assertEqual", "(first, second, msg=None)", "Fail if the two objects are unequal."),
    ("unittest", "TestCase", "assertNotEqual", "(first, second, msg=None)", "Fail if the two objects are equal."),
    ("unittest", "TestCase", "assertTrue", "(expr, msg=None)", "Check that the expression is true."),
    ("unittest", "TestCase", "assertFalse", "(expr, msg=None)", "Check that the expression is false."),
    ("unittest", "TestCase", "assertIs", "(expr1, expr2, msg=None)", "Test that expr1 and expr2 are the same object."),
    ("unittest", "TestCase", "assertIsNot", "(expr1, expr2, msg=None)", "Test that expr1 and expr2 are not the same object."),
    ("unittest", "TestCase", "assertIsNone", "(obj, msg=None)", "Test that obj is None."),
    ("unittest", "TestCase", "assertIsNotNone", "(obj, msg=None)", "Test that obj is not None."),
    ("unittest", "TestCase", "assertIn", "(member, container, msg=None)", "Check that member is in container."),
    ("unittest", "TestCase", "assertNotIn", "(member, container, msg=None)", "Check that member is not in container."),
    ("unittest", "TestCase", "assertIsInstance", "(obj, cls, msg=None)", "Check that obj is an instance of cls."),
    ("unittest", "TestCase", "assertRaises", "(expected_exception, *args, **kwargs)", "Fail unless an exception of class expected_exception is thrown."),
    ("unittest", "TestCase", "assertAlmostEqual", "(first, second, places=None, msg=None, delta=None)", "Fail if the two objects are unequal after rounding."),
    ("unittest", "TestCase", "setUp", "()", "Hook method for setting up the test fixture before exercising it."),
    ("unittest", "TestCase", "tearDown", "()", "Hook method for deconstructing the test fixture after testing it."),
    ("unittest", "TestCase", "setUpClass", "()", "Hook method for setting up class fixture before running tests in the class."),
    ("unittest", "TestCase", "tearDownClass", "()", "Hook method for deconstructing class fixture after running all tests in the class."),
    # fastapi
    ("fastapi", "APIRouter", "get", "(path, *args, **kwargs)", "Register a GET HTTP route."),
    ("fastapi", "APIRouter", "post", "(path, *args, **kwargs)", "Register a POST HTTP route."),
    ("fastapi", "APIRouter", "put", "(path, *args, **kwargs)", "Register a PUT HTTP route."),
    ("fastapi", "APIRouter", "delete", "(path, *args, **kwargs)", "Register a DELETE HTTP route."),
    ("fastapi", "APIRouter", "patch", "(path, *args, **kwargs)", "Register a PATCH HTTP route."),
    ("fastapi", "APIRouter", "include_router", "(router, *args, **kwargs)", "Include another APIRouter."),
    ("fastapi", "APIRouter", "add_api_route", "(path, endpoint, *args, **kwargs)", "Add an API route."),
    ("fastapi", "FastAPI", "get", "(path, *args, **kwargs)", "Register a GET HTTP route on the FastAPI application."),
    ("fastapi", "FastAPI", "post", "(path, *args, **kwargs)", "Register a POST HTTP route on the FastAPI application."),
    ("fastapi", "FastAPI", "include_router", "(router, *args, **kwargs)", "Include an APIRouter on the FastAPI application."),
    ("fastapi", "FastAPI", "middleware", "(middleware_type)", "Add an ASGI middleware."),
    # requests
    ("requests", "Session", "get", "(url, **kwargs) -> Response", "Sends a GET request."),
    ("requests", "Session", "post", "(url, data=None, json=None, **kwargs) -> Response", "Sends a POST request."),
    ("requests", "Session", "put", "(url, data=None, **kwargs) -> Response", "Sends a PUT request."),
    ("requests", "Session", "delete", "(url, **kwargs) -> Response", "Sends a DELETE request."),
    ("requests", "Session", "request", "(method, url, **kwargs) -> Response", "Constructs and sends a Request."),
    ("requests", "Session", "mount", "(prefix, adapter)", "Registers a connection adapter."),
    ("requests", "Session", "close", "()", "Closes all adapters and as such the session."),
    ("requests", "Response", "json", "(**kwargs)", "Returns the json-encoded content of a response."),
    ("requests", "Response", "raise_for_status", "()", "Raises HTTPError, if one occurred."),
    # pytest
    ("pytest", "fixture", "fixture", "(scope='function', params=None, autouse=False, ids=None, name=None)", "Decorator to mark a fixture factory function."),
    ("pytest", "mark", "parametrize", "(argnames, argvalues, indirect=False, ids=None, scope=None)", "Parametrize a test function call."),
    ("pytest", "raises", "raises", "(expected_exception, *args, match=None, **kwargs)", "Assert that a code block raises expected_exception."),
    # Python core builtins
    ("builtins", "dict", "get", "(key, default=None)", "Return the value for key if key is in the dictionary, else default."),
    ("builtins", "dict", "items", "()", "Return a set-like object providing a view on D's items."),
    ("builtins", "dict", "keys", "()", "Return a set-like object providing a view on D's keys."),
    ("builtins", "dict", "values", "()", "Return an object providing a view on D's values."),
    ("builtins", "dict", "update", "(other=(), **kwargs)", "Update dictionary from dict/iterable other and kwargs."),
    ("builtins", "dict", "pop", "(key, default=None)", "Remove specified key and return the corresponding value."),
    ("builtins", "list", "append", "(object)", "Append object to the end of the list."),
    ("builtins", "list", "extend", "(iterable)", "Extend list by appending elements from the iterable."),
    ("builtins", "list", "pop", "(index=-1)", "Remove and return item at index (default last)."),
    ("builtins", "set", "add", "(element)", "Add an element to a set."),
    ("builtins", "set", "discard", "(element)", "Remove an element from a set if it is a member."),
    ("builtins", "Exception", "args", "tuple", "Tuple of exception arguments."),
]


def get_relevant_stubs(imports_by_path: dict[str, list[str]] | None = None) -> list[ExternalStubRecord]:
    """
    Perform import-driven tree shaking:
    Only return external stubs for packages that are actually imported in the repo,
    plus standard core builtins.
    """
    imported_pkgs = {"builtins"}
    if imports_by_path:
        for imps in imports_by_path.values():
            for imp in imps:
                if imp:
                    imported_pkgs.add(imp.split(".")[0].strip())

    stubs: list[ExternalStubRecord] = []
    stub_id = 1
    for pkg, export_path, member_name, signature, doc_summary in CURATED_EXTERNAL_STUBS:
        if pkg in imported_pkgs or pkg == "builtins":
            stubs.append(
                ExternalStubRecord(
                    stub_id=stub_id,
                    package=pkg,
                    export_path=export_path,
                    member_name=member_name,
                    signature=signature,
                    doc_summary=doc_summary,
                )
            )
            stub_id += 1
    return stubs
