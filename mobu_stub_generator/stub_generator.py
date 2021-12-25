#
#   Code to generate a stub files
#
import importlib
import inspect
import typing
import pydoc
import time
import sys
import os
import re

from importlib import reload

from . import motionbuilder_documentation_parser as docParser

reload(docParser)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "generated-stub-files")


# ---------------------------
#     Enums And Structs
# ---------------------------


class FObjectType:
    Function = 'function'
    Class = 'class'
    Property = 'property'
    Enum = 'type'

# --------------------------------------------------------
#                    Patch Functions
# --------------------------------------------------------


def PatchGeneratedDocString(Text):
    # Replace content
    for TagName, ReplaceWith in [("<b>", ""), ("</b>", ""), ("b>", ""), ("\\", "\\\\")]:
        Text = Text.replace(TagName, ReplaceWith)

    # Patch @code, example:
    #   @code
    #   print("Hello World")
    #   @endcode
    if "@code" in Text:
        NewText = ""
        bInCodeBlock = False
        bFirstCodeLine = False
        for Line in Text.split("\n"):
            Line += "\n"
            if bInCodeBlock:
                if Line.startswith("@endcode"):
                    bInCodeBlock = False
                    Line = "\n"
                elif not Line.strip():
                    continue
                else:
                    if Line.strip().startswith("//"):
                        Line = Line.replace("//", "#")
                    if not bFirstCodeLine:
                        Line = "    %s" % Line
                bFirstCodeLine = False
            elif Line.startswith("@code"):
                bFirstCodeLine = True
                bInCodeBlock = True
                Line = "\n>>> "

            NewText += Line
        Text = NewText

    # Remove p prefix from parameters, example: pVector -> Vector
    Text = re.sub(r"\s(p)([A-Z])", r"\2", Text)

    return Text.strip()


def PatchArgumentName(Param: str):
    # Remove the 'p' prefix
    if Param.startswith("p"):
        if not (len(Param) == 2 and Param[1].isdigit()):
            Param = Param[1:]

    if Param == "True":
        Param = "bState"

    return Param


def PatchVariableType(VariableType: str, ExistingClassNames, ClassMembers = [], Default = None, bAlwaysTryToRemoveProperty = True):
    """
    Patch property types to match what's avaliable for Python.
    """
    
    if VariableType == "enum":
        return "_Enum"
    
    if not VariableType.startswith("FB"):
        if VariableType.startswith("Property"):
            NewVariableType = VariableType.replace("Property", "", 1)
            if NewVariableType in ExistingClassNames or NewVariableType in ClassMembers:
                return NewVariableType
            return Default
        
        return VariableType
        
    FBEventName = "FBEvent"
    if VariableType.startswith(FBEventName) and not (VariableType in ExistingClassNames or VariableType in ClassMembers):
        if FBEventName in ExistingClassNames or FBEventName in ClassMembers:
            return FBEventName
        
    if bAlwaysTryToRemoveProperty or VariableType not in ExistingClassNames:
        for Key, Value in docParser.CToPythonVariableTranslation.items():
            if "fbproperty%s" % Key.lower() == VariableType.lower() or "fbpropertyanimatable%s" % Key.lower() == VariableType.lower():
                return Value
        
        if VariableType.startswith("FBPropertyAnimatable"):
            NewVariableType = VariableType.replace("PropertyAnimatable", "", 1)
        else:
            NewVariableType = VariableType.replace("Property", "", 1)
        
        if NewVariableType in ExistingClassNames or NewVariableType in ClassMembers:
            return NewVariableType
        
    if VariableType in ExistingClassNames or VariableType in ClassMembers:
        return VariableType
        
    return Default


# --------------------------------------------------------
#                       Classes
# --------------------------------------------------------

class StubSettings():
    TabCharacter = "    "


class StubBaseClass():
    def __init__(self, Name = "", Indentation = 0, Settings = None) -> None:
        self.Name = Name
        self._DocString = ""
        self.SetIndentationLevel(Indentation)
        self.Settings = Settings if Settings else StubSettings()

    def SetIndentationLevel(self, Level: int):
        self._Indentation = Level

    def GetAsString(self) -> str:
        """
        Get instance as python code (in string format)
        """
        raise NotImplementedError("GetAsString() has not yet been implemented")

    def SetDocString(self, Text):
        """ Will patch the docstring before setting it """
        self._DocString = PatchGeneratedDocString(Text)

    def GetDocString(self):
        if self._DocString:
            return '"""%s"""' % self._DocString
        return ""

    def Indent(self, Text, bCurrent = False):
        Level = self._Indentation if bCurrent else self._Indentation + 1
        return "\n".join([(self.Settings.TabCharacter * Level) + Line.strip() for Line in Text.split("\n")])

    def GetRequirements(self) -> list:
        """
        Get a list of variable/class names that needs to be declared before the current object
        """
        raise NotImplementedError("GetRequirements() has not yet been implemented")


class StubClass(StubBaseClass):
    def __init__(self, Name = "", Indentation = 0, Settings = None):
        super().__init__(Name = Name, Indentation = Indentation, Settings = Settings)
        self.Parents = []
        self.StubProperties = []
        self.StubFunctions = []

    def GetRequirements(self) -> list:
        # The class parent's needs to be declared before the class
        return self.Parents

    def GetAsString(self):
        ParentClassesAsString = ','.join(self.Parents)
        ClassAsString = "class %s(%s):\n" % (self.Name, ParentClassesAsString)

        if self.GetDocString():
            ClassAsString += "%s\n" % self.Indent(self.GetDocString())

        ClassMembers = self.StubProperties + self.StubFunctions
        for StubObject in ClassMembers:
            StubObject.SetIndentationLevel(1)
            ClassAsString += "%s\n" % StubObject.GetAsString()

        # If class doesn't have any members, add a ...
        if not len(ClassMembers):
            ClassAsString += self.Indent("...")

        return ClassAsString.strip()


class StubFunction(StubBaseClass):
    def __init__(self, Name="", Indentation = 0, Settings = None):
        super().__init__(Name = Name, Indentation = Indentation, Settings = Settings)
        self.Params = []
        self.ReturnType = None
        self.bIsClassFunction = False

    def GetParametersAsString(self):
        # self.Params = [("Name", "Type")]
        ParamString = ""
        for Index, Param in enumerate(self.Params):
            if self.bIsClassFunction and Index == 0:
                ParamString += "self"
            else:
                ParamString += Param[0]
                if Param[1]:
                    ParamString += ":%s" % Param[1]
            ParamString += ","

        return ParamString[:-1]

    def GetAsString(self):
        FunctionAsString = self.Indent(
            'def %s(%s)' % (self.Name, self.GetParametersAsString()),
            bCurrent = True
        )

        if self.ReturnType and self.ReturnType != "None":
            FunctionAsString += '->%s' % self.ReturnType

        FunctionAsString += ":"

        DocString = self.GetDocString()
        if DocString:
            FunctionAsString += "\n%s\n%s" % (self.Indent(DocString), self.Indent("..."))
        else:
            FunctionAsString += "..."

        return FunctionAsString


class StubProperty(StubBaseClass):
    def __init__(self, Name="", Indentation = 0, Settings = None):
        super().__init__(Name=Name, Indentation = Indentation, Settings = Settings)
        self._Type = None

    def GetType(self):
        if self._Type:
            return self._Type
        return "property"

    def SetType(self, Type):
        self._Type = Type

    def GetAsString(self):
        PropertyAsString = self.Indent("%s:%s" % (self.Name, self.GetType()), bCurrent = True)
        if self.GetDocString():
            PropertyAsString += "\n"
            PropertyAsString += self.Indent(self.GetDocString(), bCurrent = True)

        return PropertyAsString


class GeneratedPythonDocumentation():
    """ pyfbsdk comes with a pyfbsdk_gen_doc.py, containing some doc strings etc. """
    def __init__(self, ModuleName):
        if os.path.isabs(ModuleName):
            # TODO: Load module from abs path instead (using importlib)
            raise Exception("Absolute path to module is currently not supported!\nWhen trying to load: %s" % ModuleName)
        
        ImportedModule = importlib.import_module(ModuleName)
        self.Members = dict(inspect.getmembers(ImportedModule))
        
    def GetMemberByName(self, Name):
        return self.Members.get(Name)
    
    def GetDocString(self, Name):
        Member = self.GetMemberByName(Name)
        return Member.__doc__ if Member else ""


# --------------------------------------------------------
#                Helper functions
# --------------------------------------------------------

def GetObjectType(Object):
    """ Get object type as a string """
    return type(Object).__name__


def IsPrivate(Object):
    """ Check if the name of an object begins with a underscore """
    return Object.__name__.startswith("_")


def GetArgumentsFromFunction(Function):
    DocString = Function.__doc__
    HelpFunction = DocString.split("->", 1)[0]
    HelpArgumentString = HelpFunction.split("(", 1)[1].strip()[:-1]
    HelpArgumentString = HelpArgumentString.replace("]", "").replace("[", "")
    HelpArguments = HelpArgumentString.split(",")
    ReturnValue = []
    for Argument in HelpArguments:
        if not Argument:
            continue
        Type, ArgName = Argument.strip().split(")")
        ReturnValue.append((ArgName.strip(), Type[1:].strip()))
    return ReturnValue


def GetClassParents(Class):
    return Class.__bases__


def GetClassParentNames(Class):
    ParentClassNames = []
    for Parent in GetClassParents(Class):
        ParentClassName = Parent.__name__
        if ParentClassName == "instance":
            ParentClassName = ""

        elif ParentClassName == "enum":
            ParentClassName = "_Enum"

        ParentClassNames.append(ParentClassName)

    return ParentClassNames


def GetClassMembers(Class):
    IgnoreMembers = ["names", "values", "__slots__", "__instance_size__"]
    Members = inspect.getmembers(Class)
    ParentClass = GetClassParents(Class)[0]
    UniqueMemebers = [x for x in Members if not hasattr(ParentClass, x[0]) and x[0] not in IgnoreMembers and not x[0].startswith("__")]
    return UniqueMemebers


def SortClasses(Classes: list):
    """ 
    Sort classes based on their parent class
    If a class has another class as their parent class, it'll be placed later in the list
    """
    ClassNames = [x.Name for x in Classes]

    i = 0
    while (i < len(Classes)):
        # Check if class has any required classes that needs to be defined before it (aka. parent classes)
        Requirements = Classes[i].GetRequirements()
        if Requirements:
            # Get the required class that has the highest index in the list
            RequiredIndices = [ClassNames.index(x) for x in Requirements if x in ClassNames]
            RequiredMaxIndex = max(RequiredIndices) if RequiredIndices else -1

            # If current index is lower than the highest required index, move current index to be just below the required one.
            if RequiredMaxIndex > i:
                Classes.insert(RequiredMaxIndex + 1, Classes.pop(i))
                ClassNames.insert(RequiredMaxIndex + 1, ClassNames.pop(i))
                i -= 1  # Because we moved current index away, re-itterate over the same index once more.

        i += 1

    return Classes

def GetReturnTypeFromDocString(Function):
    ReturnType = Function.__doc__.split("->", 1)[1].strip()
    if "\n" in ReturnType:
        ReturnType = ReturnType.split("\n")[0].strip()
    if ReturnType.endswith(":"):
        ReturnType = ReturnType[:-1].strip()
        
    return ReturnType

# --------------------------------------------------------
#                   Generate Functions
# --------------------------------------------------------

def GenerateStubClassFunction(Function, DocMembers, MoBuDocumentation:docParser.MotionBuilderDocumentation = None):
    StubFunctionInstance = GenerateStubFunction(Function, DocMembers)
    StubFunctionInstance.bIsClassFunction = True
    
    return StubFunctionInstance


def GenerateStubFunction(Function, DocMembers, MoBuDocumentation:docParser.MotionBuilderDocumentation = None):
    FunctionName: str = Function.__name__

    StubFunctionInstance = StubFunction(FunctionName)

    # Parameters
    Parameters = GetArgumentsFromFunction(Function)

    DocRef = DocMembers.get(FunctionName)
    if DocRef:
        StubFunctionInstance.SetDocString(DocRef.__doc__)
        DocArguments = inspect.getargspec(DocRef).args
        Parameters = [(PatchArgumentName(Name), Arg[1]) for Name, Arg in zip(DocArguments, Parameters)]
    StubFunctionInstance.Params = Parameters

    # Return Type
    StubFunctionInstance.ReturnType = GetReturnTypeFromDocString(Function)

    return StubFunctionInstance


def GenerateStubClass(Module, Class, GeneratedPyDoc, AllClassNames, MoBuDocumentation: docParser.MotionBuilderDocumentation = None, bIsEnum = False):
    ClassName: str = Class.__name__
    DocClasses = [x for x in GeneratedPyDoc if GetObjectType(x) in ["class", "type"]]
    DocMemberNames = [x.__name__ for x in DocClasses]

    StubClassInstance = StubClass(ClassName)
    StubClassInstance.Parents = GetClassParentNames(Class)

    Page = MoBuDocumentation.GetSDKClassByName(ClassName) if MoBuDocumentation else None

    # TODO: DocMembers/DocGenRef etc. could be a class
    DocGenRef = GeneratedPyDoc.get(ClassName)
    DocGenMembers = {}
    if DocGenRef:
        StubClassInstance.SetDocString(DocGenRef.__doc__)
        DocGenMembers = dict(GetClassMembers(DocGenRef))

    ClassMembers = GetClassMembers(Class)
    ClassMemberNames = [x[0] for x in ClassMembers]
    for Name, Reference in ClassMembers:
        MemberType = GetObjectType(Reference)
        WebDocMember = Page.GetMember(Name) if Page else None
        if MemberType == FObjectType.Function:
            try:
                StubClassInstance.StubFunctions.append(
                    GenerateStubClassFunction(Reference, DocGenMembers)
                )
            except:
                pass  # print("Failed for %s" % Name)
        else:
            Property = StubProperty(Name)
            # Enums should have their 'self' as type
            if bIsEnum:
                Property.SetType(ClassName)
                
            else:
                Type = WebDocMember.GetType(bConvertToPython = True) if WebDocMember else None
                if not Type:
                    try:
                        exec("import %s" % Module.__name__)
                        Type = eval("type(%s.%s().%s).__name__" % (Module.__name__, ClassName, Name))
                    except Exception as e:
                        if Module.__name__ == "pyfbsdk":
                            try:
                                if eval("issubclass(%s.%s, %s.FBModel)" % (Module.__name__, ClassName, Module.__name__)):
                                    Type = eval("type(%s.%s('stub-generator-temp').%s).__name__" % (Module.__name__, ClassName, Name))
                            except Exception as e:
                                pass

                    if Type == "NoneType":
                        Type = None

                if Type:
                    Property.SetType(PatchVariableType(Type, AllClassNames, ClassMemberNames))

            StubClassInstance.StubProperties.append(Property)
            PropertyDocGenRef = DocGenMembers.get(Name)

            if PropertyDocGenRef:
                Property.SetDocString(PropertyDocGenRef.__doc__)

    return StubClassInstance


# --------------------------------------------------------
#                   Main generate function
# --------------------------------------------------------

def GenerateStub(Module, Filepath: str, SourcePyFile = "", DocumentationVersion: int = None):
    """
    Generate a stubfile

    * Module: Reference to a module to generate a stubfile
    * Filepath: The output abs filepath
    * SourcePyFile: If there exists a source .py file with doc comments (like pyfbsdk_gen_doc.py)
    """
    StartTime = time.time()

    # Create a documentation instance
    MoBuDocumentation = None
    if DocumentationVersion:
        SupportedDocumentationVersion = docParser.GetClosestSupportedMotionBuilderVersion(DocumentationVersion)
        MoBuDocumentation = docParser.MotionBuilderDocumentation(SupportedDocumentationVersion, bCache = True)

    # Get all members from the pre-generated doc/stub file
    GeneratedPyDoc = GeneratedPythonDocumentation(SourcePyFile) if SourcePyFile else None
    ImportedModule = importlib.import_module(SourcePyFile)
    GeneratedPyDoc = dict(inspect.getmembers(ImportedModule))

    # Get all Functions, Classes etc. inside of the module
    Functions = [x[1] for x in inspect.getmembers(Module) if GetObjectType(x[1]) == FObjectType.Function and not IsPrivate(x[1])]
    Classes = [x[1] for x in inspect.getmembers(Module) if GetObjectType(x[1]) == FObjectType.Class]
    Enums = [x[1] for x in inspect.getmembers(Module) if GetObjectType(x[1]) == FObjectType.Enum]
    Misc = [x for x in inspect.getmembers(Module) if GetObjectType(x[1]) not in [FObjectType.Function, FObjectType.Class, FObjectType.Enum]]
    AllClassNames = [x.__name__ for x in Classes + Enums]

    # Construct stub class instances based on all functions & classes found in the module
    StubFunctions = [GenerateStubFunction(x, GeneratedPyDoc, MoBuDocumentation) for x in Functions]
    StubClasses = [GenerateStubClass(Module, x, GeneratedPyDoc, AllClassNames, MoBuDocumentation) for x in Classes]
    StubEnums = [GenerateStubClass(Module,x, GeneratedPyDoc, AllClassNames, bIsEnum = True) for x in Enums]

    Classes = SortClasses(StubClasses)

    #
    # Generate the stub file content as a string
    #

    StubFileContent = ""

    # Extra custom additions
    AdditionsFilepath = os.path.join(os.path.dirname(__file__), "additions_%s.py" % Module.__name__)
    if os.path.isfile(AdditionsFilepath):
        with open(AdditionsFilepath, 'r') as File:
            StubFileContent += "%s\n" % File.read()

    # Add Enums, Classes & Functions to the string
    StubFileContent += "%s\n" % "\n".join([x.GetAsString() for x in StubEnums + StubClasses + StubFunctions])

    # Write content into the file
    with open(Filepath, "w+") as File:
        File.write(StubFileContent)

    # Print how long it took to generate the stub file
    ElapsedTime = time.time() - StartTime
    print("Generating stub for module '%s' took %ss" % (Module.__name__, ElapsedTime))

    return True