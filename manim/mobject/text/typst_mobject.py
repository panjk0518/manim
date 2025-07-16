r"""Mobjects representing typstt rendered using Typst.

.. important::

   See the corresponding tutorial :ref:`rendering-with-typst`

.. note::

   Just as you can use :class:`~.Typstt` (from the module :mod:`~.typstt_mobject`) to add typstt to your videos, you can use :class:`~.Typst` and :class:`~.MathTypst` to insert Typst.

"""

from __future__ import annotations

from manim.utils.color import BLACK, ManimColor, ParsableManimColor

__all__ = [
    "SingleStringMathTypst",
    "MathTypst",
    "Typst",
    "TypstBulletedList",
    "TypstTitle",
]


import itertools as it
import operator as op
import re
from collections.abc import Iterable
from functools import reduce
from typsttwrap import dedent
from typing import Any

from manim import config, logger
from manim.constants import *
from manim.mobject.geometry.line import Line
from manim.mobject.svg.svg_mobject import SVGMobject
from manim.mobject.types.vectorized_mobject import VGroup, VMobject
from manim.utils.typst import TypstTemplate
from manim.utils.typst_file_writing import typst_to_svg_file

typst_string_to_mob_map = {}


class SingleStringMathTypst(SVGMobject):
    """Elementary building block for rendering typstt with Typst.

    Tests
    -----
    Check that creating a :class:`~.SingleStringMathTypst` object works::

        >>> SingleStringMathTypst('Test') # doctest: +SKIP
        SingleStringMathTypst('Test')
    """

    def __init__(
        self,
        typst_string: str,
        stroke_width: float = 0,
        should_center: bool = True,
        height: float | None = None,
        organize_left_to_right: bool = False,
        typst_environment: str = "align*",
        typst_template: TypstTemplate | None = None,
        font_size: float = DEFAULT_FONT_SIZE,
        color: ParsableManimColor | None = None,
        **kwargs,
    ):
        if color is None:
            color = VMobject().color

        self._font_size = font_size
        self.organize_left_to_right = organize_left_to_right
        self.typst_environment = typst_environment
        if typst_template is None:
            typst_template = config["typst_template"]
        self.typst_template = typst_template

        assert isinstance(typst_string, str)
        self.typst_string = typst_string
        file_name = typst_to_svg_file(
            self._get_modified_expression(typst_string),
            environment=self.typst_environment,
            typst_template=self.typst_template,
        )
        super().__init__(
            file_name=file_name,
            should_center=should_center,
            stroke_width=stroke_width,
            height=height,
            color=color,
            path_string_config={
                "should_subdivide_sharp_curves": True,
                "should_remove_null_curves": True,
            },
            **kwargs,
        )
        self.init_colors()

        # used for scaling via font_size.setter
        self.initial_height = self.height

        if height is None:
            self.font_size = self._font_size

        if self.organize_left_to_right:
            self._organize_submobjects_left_to_right()

    def __repr__(self):
        return f"{type(self).__name__}({repr(self.typst_string)})"

    @property
    def font_size(self):
        """The font size of the typst mobject."""
        return self.height / self.initial_height / SCALE_FACTOR_PER_FONT_POINT

    @font_size.setter
    def font_size(self, font_val):
        if font_val <= 0:
            raise ValueError("font_size must be greater than 0.")
        elif self.height > 0:
            # sometimes manim generates a SingleStringMathex mobject with 0 height.
            # can't be scaled regardless and will error without the elif.

            # scale to a factor of the initial height so that setting
            # font_size does not depend on current size.
            self.scale(font_val / self.font_size)

    def _get_modified_expression(self, typst_string):
        result = typst_string
        result = result.strip()
        result = self._modify_special_strings(result)
        return result

    def _modify_special_strings(self, typst):
        typst = typst.strip()
        should_add_filler = reduce(
            op.or_,
            [
                # Fraction line needs something to be over
                typst == "overline",
                typst == "overline{",
                # Make sure sqrt has overbar
                typst == "sqrt",
                typst == "sqrt(",
                # Need to add blank subscript or superscript
                typst.endswith("_"),
                typst.endswith("^"),
                typst.endswith("dot"),
            ],
        )

        if should_add_filler:
            filler = " "
            typst += filler

        # Typst does not have any command like the LaTeX "\\substack" so let's comment it. 
        # if typst == "\\substack":
        #     typst = "\\quad"

        if typst == "":
            typst = "#h(1)"

        # To keep files from starting with a line break
        if typst.startswith("\\ "):
            typst = typst.replace("\\ ", "\\ #h(1cm) \\ ")

        # Typst automatically handles the size of delimiters so there is no \left and \right in Typst
        # , thus this handling is unneeded. 
        # Handle imbalanced \left and \right
        # num_lefts, num_rights = (
        #     len([s for s in typst.split(substr)[1:] if s and s[0] in "(){}[]|.\\"])
        #     for substr in ("\\left", "\\right")
        # )
        # if num_lefts != num_rights:
        #     typst = typst.replace("\\left", "\\big")
        #     typst = typst.replace("\\right", "\\big")

        typst = self._remove_stray_braces(typst)

        # There is no beginning mark and ending mark in Typst so let's comment this. 
        # for contypstt in ["array"]:
        #     begin_in = ("\\begin{%s}" % contypstt) in typst  # noqa: UP031
        #     end_in = ("\\end{%s}" % contypstt) in typst  # noqa: UP031
        #     if begin_in ^ end_in:
        #         # Just turn this into a blank string,
        #         # which means caller should leave a
        #         # stray \\begin{...} with other symbols
        #         typst = ""
        return typst

    def _remove_stray_braces(self, typst):
        r"""
        Makes :class:`~.MathTypst` resilient to unmatched braces and other delimiters.

        This is important when the braces in the Typst code are spread over
        multiple arguments as in, e.g., ``MathTypst(r"e^{i", r" tau} = 1")``.
        """
        # "\{" does not count (it's a brace literal)
        num_braces_lefts = typst.count("{") - typst.count("\\{")
        num_braces_rights = typst.count("}") - typst.count("\\}")
        while num_braces_rights > num_braces_lefts:
            typst = "{" + typst
            num_braces_lefts += 1
        while num_braces_lefts > num_braces_rights:
            typst = typst + "}"
            num_braces_rights += 1
        # Well, the same for parentheses and square brackets for they are also importent syntax marks in Typst. 
        num_parentheses_lefts = typst.count("(") - typst.count("\\(")
        num_parentheses_rights = typst.count(")") - typst.count("\\)")
        while num_parentheses_rights > num_parentheses_lefts:
            typst = "(" + typst
            num_parentheses_lefts += 1
        while num_parentheses_lefts > num_parentheses_rights:
            typst = typst + ")"
            num_parentheses_rights += 1
        num_brackets_lefts = typst.count("[") - typst.count("\\[")
        num_brackets_rights = typst.count("]") - typst.count("\\]")
        while num_brackets_rights > num_brackets_lefts:
            typst = "[" + typst
            num_brackets_lefts += 1
        while num_brackets_lefts > num_brackets_rights:
            typst = typst + "]"
            num_brackets_rights += 1
        return typst

    def _organize_submobjects_left_to_right(self):
        self.sort(lambda p: p[0])
        return self

    def get_typst_string(self):
        return self.typst_string

    def init_colors(self, propagate_colors=True):
        for submobject in self.submobjects:
            # needed to preserve original (non-black)
            # TeX colors of individual submobjects
            if submobject.color != BLACK:
                continue
            submobject.color = self.color
            if config.renderer == RendererType.OPENGL:
                submobject.init_colors()
            elif config.renderer == RendererType.CAIRO:
                submobject.init_colors(propagate_colors=propagate_colors)


class MathTypst(SingleStringMathTypst):
    r"""A string compiled with Typst in math mode.

    Examples
    --------
    .. manim:: Formula
        :save_last_frame:

        class Formula(Scene):
            def construct(self):
                t = MathTypst(r"int_a^b f'(x) dx = f(b)- f(a)")
                self.add(t)

    Tests
    -----
    Check that creating a :class:`~.MathTypst` works::

        >>> MathTypst('a^2 + b^2 = c^2') # doctest: +SKIP
        MathTypst('a^2 + b^2 = c^2')

    Check that #{} splitting works correctly::
        * WELL, Typst DOES NOT offer an elegant splitter we can use. An UGLY solution is to use empty code blocks for splitting. 
        * NOTE: THIS DOES NOT BEHAVE LIKE THE LATEX {{}} SPLIT. You HAVE TO put a #{} at EACH SPACING where you want to split. 
        >>> t1 = MathTypst('a #{} + #{} b #{} = #{} c ') # doctest: +SKIP
        >>> len(t1.submobjects) # doctest: +SKIP
        5
        >>> t2 = MathTypst(r"1 / (a + b sqrt(2))") # doctest: +SKIP
        >>> len(t2.submobjects) # doctest: +SKIP
        1

    """

    def __init__(
        self,
        *typst_strings,
        arg_separator: str = " ",
        substrings_to_isolate: Iterable[str] | None = None,
        typst_to_color_map: dict[str, ManimColor] = None,
        typst_environment: str = "align*",
        **kwargs,
    ):
        self.typst_template = kwargs.pop("typst_template", config["typst_template"])
        self.arg_separator = arg_separator
        self.substrings_to_isolate = (
            [] if substrings_to_isolate is None else substrings_to_isolate
        )
        self.typst_to_color_map = typst_to_color_map
        if self.typst_to_color_map is None:
            self.typst_to_color_map = {}
        self.typst_environment = typst_environment
        self.brace_notation_split_occurred = False
        self.typst_strings = self._break_up_typst_strings(typst_strings)
        try:
            super().__init__(
                self.arg_separator.join(self.typst_strings),
                typst_environment=self.typst_environment,
                typst_template=self.typst_template,
                **kwargs,
            )
            self._break_up_by_substrings()
        except ValueError as compilation_error:
            if self.brace_notation_split_occurred:
                logger.error(
                    dedent(
                        # """\
                        # A group of empty code blocks, {{ ... }}, was detected in
                        # your string. Manim splits TeX strings at the double
                        # braces, which might have caused the current
                        # compilation error. If you didn't use the double brace
                        # split intentionally, add spaces between the braces to
                        # avoid the automatic splitting: {{ ... }} --> { { ... } }.
                        # """,
                        """\
                        We had an error splitting the Typst strings. Manim splits 
                        Typst strings at the empty code blocks #{}. If you didn't 
                        use the empty code blocks split intentionally, add a space 
                        between the braces of code blocks to avoid the automatic 
                        splitting: ${} --> ${ }
                        Meanwhile, Typst code blocks can not be splitted. Remove all 
                        empty code blocks #{} that are inside code blocks.
                        """
                    ),
                )
            raise compilation_error
        self.set_color_by_typst_to_color_map(self.typst_to_color_map)

        if self.organize_left_to_right:
            self._organize_submobjects_left_to_right()

    def _break_up_typst_strings(self, typst_strings):
        # TODO: Separation Logic Rewrite
        # Separate out anything surrounded in double braces
        pre_split_length = len(typst_strings)
        typst_strings = [re.split("#\\{\\}", str(t)) for t in typst_strings]
        typst_strings = sum(typst_strings, [])
        if len(typst_strings) > pre_split_length:
            self.brace_notation_split_occurred = True

        # Separate out any strings specified in the isolate
        # or typst_to_color_map lists.
        patterns = []
        patterns.extend(
            [
                f"({re.escape(ss)})"
                for ss in it.chain(
                    self.substrings_to_isolate,
                    self.typst_to_color_map.keys(),
                )
            ],
        )
        pattern = "|".join(patterns)
        if pattern:
            pieces = []
            for s in typst_strings:
                pieces.extend(re.split(pattern, s))
        else:
            pieces = typst_strings
        return [p for p in pieces if p]

    def _break_up_by_substrings(self):
        """
        Reorganize existing submobjects one layer
        deeper based on the structure of typst_strings (as a list
        of typst_strings)
        """
        new_submobjects = []
        curr_index = 0
        for typst_string in self.typst_strings:
            sub_typst_mob = SingleStringMathTypst(
                typst_string,
                typst_environment=self.typst_environment,
                typst_template=self.typst_template,
            )
            num_submobs = len(sub_typst_mob.submobjects)
            new_index = (
                curr_index + num_submobs + len("".join(self.arg_separator.split()))
            )
            if num_submobs == 0:
                last_submob_index = min(curr_index, len(self.submobjects) - 1)
                sub_typst_mob.move_to(self.submobjects[last_submob_index], RIGHT)
            else:
                sub_typst_mob.submobjects = self.submobjects[curr_index:new_index]
            new_submobjects.append(sub_typst_mob)
            curr_index = new_index
        self.submobjects = new_submobjects
        return self

    def get_parts_by_typst(self, typst, substring=True, case_sensitive=True):
        def test(typst1, typst2):
            if not case_sensitive:
                typst1 = typst1.lower()
                typst2 = typst2.lower()
            if substring:
                return typst1 in typst2
            else:
                return typst1 == typst2

        return VGroup(*(m for m in self.submobjects if test(typst, m.get_typst_string())))

    def get_part_by_typst(self, typst, **kwargs):
        all_parts = self.get_parts_by_typst(typst, **kwargs)
        return all_parts[0] if all_parts else None

    def set_color_by_typst(self, typst, color, **kwargs):
        parts_to_color = self.get_parts_by_typst(typst, **kwargs)
        for part in parts_to_color:
            part.set_color(color)
        return self

    def set_opacity_by_typst(
        self, typst: str, opacity: float = 0.5, remaining_opacity: float = None, **kwargs
    ):
        """
        Sets the opacity of the typst specified. If 'remaining_opacity' is specified,
        then the remaining typst will be set to that opacity.

        Parameters
        ----------
        typst
            The typst to set the opacity of.
        opacity
            Default 0.5. The opacity to set the typst to
        remaining_opacity
            Default None. The opacity to set the remaining typst to.
            If None, then the remaining typst will not be changed
        """
        if remaining_opacity is not None:
            self.set_opacity(opacity=remaining_opacity)
        for part in self.get_parts_by_typst(typst):
            part.set_opacity(opacity)
        return self

    def set_color_by_typst_to_color_map(self, typsts_to_color_map, **kwargs):
        for typsts, color in list(typsts_to_color_map.items()):
            try:
                # If the given key behaves like typst_strings
                typsts + ""
                self.set_color_by_typst(typsts, color, **kwargs)
            except TypeError:
                # If the given key is a tuple
                for typst in typsts:
                    self.set_color_by_typst(typst, color, **kwargs)
        return self

    def index_of_part(self, part):
        split_self = self.split()
        if part not in split_self:
            raise ValueError("Trying to get index of part not in MathTypst")
        return split_self.index(part)

    def index_of_part_by_typst(self, typst, **kwargs):
        part = self.get_part_by_typst(typst, **kwargs)
        return self.index_of_part(part)

    def sort_alphabetically(self):
        self.submobjects.sort(key=lambda m: m.get_typst_string())


class Typst(MathTypst):
    r"""A string compiled with Typst in normal mode.

    The color can be set using
    the ``color`` argument. Any parts of the ``typst_string`` that are colored by the
    TeX commands ``\color`` or ``\typsttcolor`` will retain their original color.

    Tests
    -----

    Check whether writing a Typst string works::

        >>> Typst('The horse does not eat cucumber salad.') # doctest: +SKIP
        Typst('The horse does not eat cucumber salad.')

    """

    def __init__(
        self,
        *typst_strings: str,
        arg_separator: str = "",
        typst_environment: str = "center",
        **kwargs: Any,
    ):
        super().__init__(
            *typst_strings,
            arg_separator=arg_separator,
            typst_environment=typst_environment,
            **kwargs,
        )


class BulletedList(Typst):
    """A bulleted list.

    Examples
    --------

    .. manim:: BulletedListExample
        :save_last_frame:

        class BulletedListExample(Scene):
            def construct(self):
                blist = BulletedList("Item 1", "Item 2", "Item 3", height=2, width=2)
                blist.set_color_by_typst("Item 1", RED)
                blist.set_color_by_typst("Item 2", GREEN)
                blist.set_color_by_typst("Item 3", BLUE)
                self.add(blist)
    """

    def __init__(
        self,
        *items,
        buff=MED_LARGE_BUFF,
        dot_scale_factor=2,
        typst_environment=None,
        **kwargs,
    ):
        self.buff = buff
        self.dot_scale_factor = dot_scale_factor
        self.typst_environment = typst_environment
        line_separated_items = [s + "\\\\" for s in items]
        super().__init__(
            *line_separated_items, typst_environment=typst_environment, **kwargs
        )
        for part in self:
            dot = MathTypst("\\cdot").scale(self.dot_scale_factor)
            dot.next_to(part[0], LEFT, SMALL_BUFF)
            part.add_to_back(dot)
        self.arrange(DOWN, aligned_edge=LEFT, buff=self.buff)

    def fade_all_but(self, index_or_string, opacity=0.5):
        arg = index_or_string
        if isinstance(arg, str):
            part = self.get_part_by_typst(arg)
        elif isinstance(arg, int):
            part = self.submobjects[arg]
        else:
            raise TypeError(f"Expected int or string, got {arg}")
        for other_part in self.submobjects:
            if other_part is part:
                other_part.set_fill(opacity=1)
            else:
                other_part.set_fill(opacity=opacity)


class Title(Typst):
    """A mobject representing an underlined title.

    Examples
    --------
    .. manim:: TitleExample
        :save_last_frame:

        import manim

        class TitleExample(Scene):
            def construct(self):
                banner = ManimBanner()
                title = Title(f"Manim version {manim.__version__}")
                self.add(banner, title)

    """

    def __init__(
        self,
        *typstt_parts,
        include_underline=True,
        match_underline_width_to_typstt=False,
        underline_buff=MED_SMALL_BUFF,
        **kwargs,
    ):
        self.include_underline = include_underline
        self.match_underline_width_to_typstt = match_underline_width_to_typstt
        self.underline_buff = underline_buff
        super().__init__(*typstt_parts, **kwargs)
        self.to_edge(UP)
        if self.include_underline:
            underline_width = config["frame_width"] - 2
            underline = Line(LEFT, RIGHT)
            underline.next_to(self, DOWN, buff=self.underline_buff)
            if self.match_underline_width_to_typstt:
                underline.match_width(self)
            else:
                underline.width = underline_width
            self.add(underline)
            self.underline = underline
