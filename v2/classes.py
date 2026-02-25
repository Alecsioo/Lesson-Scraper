from dataclasses import dataclass, field


@dataclass
class Course:
    id: str
    levels: list[Level] = field(default_factory=list) # A1, A2, Travel, Pronunciation, ...


@dataclass
class Level:
    id: str
    level: str
    chapters: list[Chapter] = field(default_factory=list)


@dataclass
class Chapter:
    name: str
    lessons: list[Lesson] = field(default_factory=list)


@dataclass
class Lesson:
    id: str
    type: str
