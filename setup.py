"""Package the bot"""

import setuptools
import steamscordbot

REQUIREMENTS = [
    "steam",
    "discord.py",
    "requests"
]

def get_long_description():
    with open("README.md", "r") as readme_file:
        readme = readme_file.read()
        return readme[readme.find("# steamscordbot"):]

if __name__ == '__main__':
    setuptools.setup(
        name=steamscordbot.__name__,
        version=steamscordbot.__version__,
        author=steamscordbot.__author__,
        author_email="esabouraud@users.noreply.github.com",
        description=steamscordbot.__doc__,
        long_description=get_long_description(),
        long_description_content_type="text/markdown",
        url="https://github.com/esabouraud/steamscordbot",
        python_requires=">=3.8",
        packages=[steamscordbot.__package__],
        install_requires=REQUIREMENTS,
        license="License :: OSI Approved :: BSD License",
        classifiers=[
            "Development Status :: 4 - Beta",
            "Programming Language :: Python :: 3.8",
            "License :: OSI Approved :: BSD License",
            "Operating System :: OS Independent",
            "Topic :: Communications :: Chat",
            "Topic :: Games/Entertainment"
        ]
    )
