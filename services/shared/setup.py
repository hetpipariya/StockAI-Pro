from setuptools import setup, find_packages

setup(
    name="stockai_shared",
    version="2.0.0",
    packages=find_packages(),
    install_requires=["pydantic", "redis", "sqlalchemy", "passlib", "bcrypt==4.0.1"],
)