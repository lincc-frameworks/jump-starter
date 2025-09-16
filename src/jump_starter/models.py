from datetime import datetime
from typing import Union

from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_core import PydanticCustomError


class Template(BaseModel):
    """Represents a template for code replacement in the questionnaire."""

    replacement: str
    code: str


class Answer(BaseModel):
    """Represents an answer to a question in the questionnaire."""

    answer: str
    tooltip: str = ""
    templates: list[Template] = Field(default_factory=list)
    goto: str | None = None
    commentary: str = ""


class Question(BaseModel):
    """Represents a question in the questionnaire."""

    question: str
    id: str | None = None
    variable: str | None = None
    answers: list[Answer]
    next_question: str | None = None


class Case(BaseModel):
    """Represents a case in a switch statement within the questionnaire."""

    value: int | None = None
    questions: list[Union[Question, "Switch"]]


class Switch(BaseModel):
    """Represents a switch statement in the questionnaire."""

    switch: str
    id: str | None = None
    cases: list[Case]


# Rebuild models to support self-referencing types and forward references
Question.model_rebuild()
Answer.model_rebuild()
Case.model_rebuild()
Switch.model_rebuild()


class QuestionAnswer(BaseModel):
    """Represents a user's answer to a question."""

    question: str
    answer: str
    value: int


class QuestionAnswers(BaseModel):
    """Represents a collection of user answers to questions."""

    answers: list[QuestionAnswer] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


class Questionnaire(BaseModel):
    """Represents a questionnaire with an initial template and a list of questions."""

    initial_template: str
    initial_commentary: str = ""
    feedback_url: str | None = None
    questions: list[Question | Switch]
    _question_map: dict[str, Union[Question, Switch]] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="after")
    def validate_and_build_id_map(self):
        """Validates the questionnaire structure and builds a mapping of IDs to nodes."""
        errors = []
        id_to_node: dict[str, Union[Question, Switch]] = {}
        refs: list[tuple[tuple, str]] = []  # list of (loc_tuple, referenced_id)

        def walk(nodes: list[Union[Question, Switch]], loc: tuple = ()):
            for i, node in enumerate(nodes):
                node_loc = (*loc, "questions", i)

                # QUESTION node
                if isinstance(node, Question):
                    id = node.id if node.id else node.question
                    if id in id_to_node:
                        errors.append(
                            PydanticCustomError(
                                "duplicate_id",
                                "Duplicate id '{id}'",
                                {"id": id},
                            ).as_error(loc=node_loc + ("id",))
                        )
                    else:
                        id_to_node[id] = node

                    if node.next_question:
                        refs.append((node_loc + ("next_question",), node.next_question))

                    for j, ans in enumerate(node.answers):
                        if ans.goto:
                            refs.append((node_loc + ("answers", j, "goto"), ans.goto))

                # SWITCH node
                elif isinstance(node, Switch):
                    if node.id:
                        if node.id in id_to_node:
                            errors.append(
                                PydanticCustomError(
                                    "duplicate_id",
                                    "Duplicate id '{id}'",
                                    {"id": node.id},
                                ).as_error(loc=node_loc + ("id",))
                            )
                        else:
                            id_to_node[node.id] = node

                    for k, case in enumerate(node.cases):
                        # descend into case.questions; the walker will prepend "questions" again
                        walk(case.questions, node_loc + ("cases", k))

                else:
                    # unexpected type — ignore or optionally raise
                    pass

        # single traversal to collect ids and references
        walk(self.questions)

        # validate all references (collected above)
        for ref_loc, ref_id in refs:
            if ref_id not in id_to_node:
                errors.append(
                    PydanticCustomError(
                        "invalid_reference",
                        "Unknown reference '{ref}'",
                        {"ref": ref_id},
                    ).as_error(loc=ref_loc)
                )

        if errors:
            # raise structured pydantic ValidationError (attached to exact locs)
            raise ValidationError.from_exception_data(self.__class__.__name__, errors)

        self._question_map = id_to_node

        return self
