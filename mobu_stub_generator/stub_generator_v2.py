from __future__ import annotations

import pyfbsdk

import importlib
import inspect
import typing
import pydoc
import time
import sys
import os
import re

from importlib import reload
from typing import List, overload

sys.path.append(os.path.dirname(__file__))

import motionbuilder_documentation_parser as docParser


reload(docParser)

DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "generated-stub-files")
ADDITIONS_FILEPATH = os.path.join(os.path.dirname(__file__), "additions_pyfbsdk.py")
TAB_CHARACTER = "    "

# TODO: Broken stuff:
# * FBModel.GetHierarchyWorldMatrices() - First param in the docs doesn't exists in the python version  
# * FBInterpolateRotation() - Both of them use the same documentation :/

# -------------------------------------------------------------
#                         Translations
# -------------------------------------------------------------

# In the online C++ MotionBuilder documentation these classes/functions have following aliases:
TranslationDocumentationClassNames = {
    "FBVector3d": "FBVector3",
    "FBVector4d": "FBVector4"
}

TranslationDocumentationMethodNames = {
    "__sub__": "operator-",
    "__getitem__": "operator[]",
}

PropertyTypeTranslation = {
    "FBPropertyString": "str",
    "FBPropertyInt": "int",
    "FBPropertyFloat": "float",
    "FBPropertyDouble": "float",
    "FBPropertyAnimatableDouble": "float",
    "FBPropertyBool": "bool",
    "FBPropertyAnimatableBool": "bool",
}


# -------------------------------------------------------------
#                       Structs & Enums
# -------------------------------------------------------------

class FObjectType:
    Function = 'function'
    Class = 'class'
    Property = 'property'
    Enum = 'type'


# -------------------------------------------------------------
#                       Helper Functios
# -------------------------------------------------------------


def GetMotionBuilderVersion():
    """ Get the current version of MotionBuilder """
    return int(2000 + pyfbsdk.FBSystem().Version / 1000)


def GetObjectName(Object):
    return Object.__name__


def GetObjectType(Object) -> FObjectType:
    """ Get object type as a string """
    return GetObjectName(type(Object))


def IsPrivate(Object):
    """ Check if the name of an object begins with a underscore """
    return GetObjectName(Object).startswith("_")


def Indent(Text: str):
    return TAB_CHARACTER + ("\n%s" % TAB_CHARACTER).join(Text.split("\n"))


def IsMethodStatic(Class, MethodName: str):
    """ 
    Check if a method is static
    Args:
        - Class: reference to the class
        - Method: Name of the method
    """
    return isinstance(inspect.getattr_static(Class, MethodName), staticmethod)


# -------------------------------------------------------------
#                       Functions
# -------------------------------------------------------------

def GetCustomAdditions():
    with open(ADDITIONS_FILEPATH, 'r') as File:
        return File.read().strip() + "\n"


def GetPyfbsdkContent():
    """ 
    Get all members in the pyfbsdk module
    returns: a tuple with (Functions, Classes, Enums)
    """
    Functions = [x[1] for x in inspect.getmembers(pyfbsdk) if GetObjectType(x[1]) == FObjectType.Function and not IsPrivate(x[1])]
    Classes = [x[1] for x in inspect.getmembers(pyfbsdk) if GetObjectType(x[1]) == FObjectType.Class]
    Enums = [x[1] for x in inspect.getmembers(pyfbsdk) if GetObjectType(x[1]) == FObjectType.Enum]

    return (Functions, Classes, Enums)


def GetClassParents(Class):
    return Class.__bases__


def GetUniqueClassMembers(Class, Ignore = [], AllowedOverrides = []):
    """ 
    Args:
        - Class {object}: reference to the class
        - Ignore {List[str]}: 
        - AlwaysAllow {List[str]}: Always allowed members named x, even if they exists in the parent class

    Returns: tuple("Name", Reference)
    """
    Members = inspect.getmembers(Class)
    ParentClass = GetClassParents(Class)[0]
    UniqueMemebers = [x for x in Members if (not hasattr(ParentClass, x[0]) and x[0] not in Ignore) or x[0] in AllowedOverrides]  # and not x[0].startswith("__")

    return UniqueMemebers


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


def GetFunctionInfoFromDocString(Function):
    """
    Get Parameters & Return type from the docstring, can return multiple results if overload functions exists.

    Returns: a list of tuple([Parameters], ReturnType)
    """
    def _GenerateParams(ParamsString, DefaultValue = None):
        """ 
        Parse a param string that looks something like this:
        "(FBVector4d)arg1, (FBVector4d)arg2, (FBVector4d)arg3"
        and generate StubParameter instances from it
        """
        Params = []
        for Param in ParamsString.split(","):
            # Param will now look something like this: '(str)arg1'
            ParamType, _, ParamName = Param.strip().partition(")")
            ParameterInstance = StubParameter(ParamName, ParamType[1:], DefaultValue = DefaultValue)
            Params.append(ParameterInstance)
        return Params

    FunctionParamters = []
    # Read the docstring and split it up if there are multiple function overrides
    FunctionsDocs = [x for x in Function.__doc__.split("\n") if x]
    for Doc in FunctionsDocs:
        # 'Doc' will now look something like this:
        # ShowToolByName( (str)arg1 [, (object)arg2]) -> object
        Doc = Doc.partition("(")[2]  # Remove function name
        Params, _, ReturnType = Doc.rpartition("->")

        # Split params into required & optional
        Params = Params.rpartition(")")[0]
        RequiredParams, _, OptionalParams = Params.partition("[")
        OptionalParams = OptionalParams.replace("[", "").replace("]", "").lstrip(',')

        Params = []
        if RequiredParams.strip():
            Params += _GenerateParams(RequiredParams)
        if OptionalParams.strip():
            Params += _GenerateParams(OptionalParams, DefaultValue = "None")

        FunctionParamters.append(
            (Params, ReturnType.strip())
        )

    return FunctionParamters


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


# -------------------------------------------------------------
#                       Classes
# -------------------------------------------------------------


class StubBaseClass():
    def __init__(self, Name = "") -> None:
        self.Name: str = Name
        self.DocString = ""

    def GetAsString(self) -> str:
        """
        Get instance as python code (in string format)
        """
        raise NotImplementedError("GetAsString() has not yet been implemented")

    def GetDocString(self):
        if self.DocString:
            return '"""%s"""' % self.DocString
        return ""

    def GetRequirements(self) -> list:
        """
        Get a list of variable/class names that needs to be declared before the current object
        """
        raise NotImplementedError("GetRequirements() has not yet been implemented")


class StubFunction(StubBaseClass):
    def __init__(self, Name = "", Parameters = [], ReturnType = None):
        super().__init__(Name = Name)
        self._Params: List[StubParameter] = Parameters
        self.ReturnType = ReturnType
        self.bIsMethod = False
        self.bIsStatic = False
        self.bIsOverload = False

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self.Name)

    def AddParameter(self, Parameter):
        self._Params.append(Parameter)

    def GetParameters(self) -> List[StubParameter]:
        return self._Params

    def SetParameter(self, Index, Paramter):
        if Index > len(self._Params) - 1:
            raise IndexError("given parameter index is larger than the size of the paramter array")
        self._Params[Index] = Paramter

    def GetRequirements(self) -> list:
        ReturnValue = []
        for Parameter in self._Params:
            ReturnValue += Parameter.GetRequirements()
        return ReturnValue

    def GetParamsAsString(self):
        ParametersAsStrings = []
        for i, Param in enumerate(self._Params):
            if self.bIsMethod and i == 0:
                Param.Name = "self"
                Param.Type = None
            ParametersAsStrings.append(Param.GetAsString())

        return ",".join(ParametersAsStrings)

    def GetAsString(self):
        FunctionAsString = ""
        if self.bIsOverload:
            FunctionAsString += "@overload\n"
        elif self.bIsStatic:
            FunctionAsString += "@staticmethod\n"

        FunctionAsString += 'def %s(%s)' % (self.Name, self.GetParamsAsString())

        if self.ReturnType and self.ReturnType != "None":
            FunctionAsString += '->%s' % self.ReturnType

        FunctionAsString += ":"

        DocString = self.GetDocString()
        if DocString:
            FunctionAsString += "\n%s\n%s" % (Indent(DocString), Indent("..."))
        else:
            FunctionAsString += "..."

        return FunctionAsString


class StubClass(StubBaseClass):
    def __init__(self, Name = ""):
        super().__init__(Name = Name)
        self.Parents = []
        self.StubProperties = []
        self.StubFunctions: List[StubProperty] = []

    def AddFunction(self, Function: StubFunction):
        Function.bIsMethod = True  # Make function a method
        self.StubFunctions.append(Function)

    def AddProperty(self, Property: StubProperty):
        self.StubProperties.append(Property)

    def AddParent(self, Parent: str):
        self.Parents.append(Parent)

    def GetStubProperties(self) -> List[StubProperty]:
        return self.StubProperties

    def GetRequirements(self) -> list:
        # The class parent's needs to be declared before the class
        FunctionRequirements = []
        for Function in self.StubFunctions:
            FunctionRequirements += Function.GetRequirements()
        return self.Parents + FunctionRequirements

    def GetAsString(self):
        ParentClassesAsString = ','.join(self.Parents)

        ClassAsString = "class %s(%s):\n" % (self.Name, ParentClassesAsString)

        if self.GetDocString():
            ClassAsString += "%s\n" % Indent(self.GetDocString())

        ClassMembers = self.StubProperties + self.StubFunctions
        for StubObject in ClassMembers:
            ClassAsString += "%s\n" % Indent(StubObject.GetAsString())

        # If class doesn't have any members, add a ...
        if not len(ClassMembers):
            ClassAsString += Indent("...")

        return ClassAsString.strip()


class StubProperty(StubBaseClass):
    def __init__(self, Name = ""):
        super().__init__(Name = Name)
        self._Type = None

    @property
    def Type(self):
        if self._Type:
            return self._Type
        return "property"

    @Type.setter
    def Type(self, Value):
        self._Type = Value

    def GetAsString(self):
        PropertyAsString = "%s:%s" % (self.Name, self.Type)

        # Add docstring
        if self.GetDocString():
            PropertyAsString += "\n"
            PropertyAsString += self.GetDocString()

        return PropertyAsString


class StubParameter(StubBaseClass):
    def __init__(self, Name = "", Type = "", DefaultValue = None):
        super().__init__(Name = Name)
        self.Type = Type
        self.DefaultValue = DefaultValue

    def GetRequirements(self):
        if self.DefaultValue and self.DefaultValue.startswith("FB"):
            RequirementClass: str = self.DefaultValue
            if "." in RequirementClass:
                RequirementClass = RequirementClass.partition(".")[0]
            return [RequirementClass]
        return []

    def GetNiceName(self):
        ReturnValue = self.Name
        if ReturnValue.startswith("p") and not (ReturnValue[1].isnumeric()):
            ReturnValue = ReturnValue.lstrip("p")
        if self.Type == "bool":
            ReturnValue = "b%s" % ReturnValue
        return ReturnValue

    def GetAsString(self):
        ParamString = self.GetNiceName()  # PatchParameterName(self.Name)
        if self.Type and self.Type != "object":
            ParamString += ":%s" % self.Type

        if self.DefaultValue is not None:
            ParamString += "=%s" % self.DefaultValue

        return ParamString


# ---------------------------------------------------------------------------------
#                                  GENERATOR
# ---------------------------------------------------------------------------------


class PyfbsdkStubGenerator():
    def __init__(self):
        self.Functions: List[StubFunction] = []
        self.Classes: List[StubClass] = []
        self.Enums: List[StubClass] = []
        self.DocumentationParser = docParser.MotionBuilderDocumentation(GetMotionBuilderVersion(), bCache = True)

        self._AllClassNames = []
        
        self._DebugPropertiesConvertedToDefault = []

    # ---------------------------------------------------
    #                      Internal
    # --------------------------------------------------
    def GetAllClassNames(self):
        if not self._AllClassNames:
            self._AllClassNames = [x.Name for x in self.Classes + self.Enums]
        return self._AllClassNames

    def _GenerateEnumInstance(self, Class):
        """ 
        Generate a StubClass instance from a class (enum) reference

        Args:
            - Class {class}: reference to the class
        """
        # Create the stub instance
        ClassName = GetObjectName(Class)
        EnumClassInstance = StubClass(ClassName)

        # Get all members and generate stub properties of them
        ClassMemebers = GetUniqueClassMembers(Class, Ignore = ["__init__", "__slots__", "names", "values"])
        for PropertyName, PropertyReference in ClassMemebers:
            PropertyInstance = StubProperty(PropertyName)
            PropertyInstance.Type = ClassName
            EnumClassInstance.AddProperty(PropertyInstance)

        EnumClassInstance.AddParent("_Enum")

        return EnumClassInstance

    def _GenerateClassInstance(self, Class) -> StubClass:
        """ 
        Generate a StubClass instance from a class reference

        Args:
            - Class {class}: reference to the class
        """
        # Create the stub instance
        ClassName = GetObjectName(Class)
        ClassInstance = StubClass(ClassName)

        # Get all members and generate stub properties of them
        ClassMemebers = GetUniqueClassMembers(Class, Ignore = ["__instance_size__"], AllowedOverrides = ["__init__"])
        for MemberName, MemberReference in ClassMemebers:
            Type = GetObjectType(MemberReference)
            if Type == FObjectType.Function:
                for StubMethod in self._GenerateFunctionInstances(MemberReference):
                    StubMethod.bIsStatic = IsMethodStatic(Class, MemberName)
                    ClassInstance.AddFunction(StubMethod)
            elif MemberName not in ["__init__"]:
                Property = StubProperty(MemberName)
                Property.Type = GetObjectType(MemberReference)
                ClassInstance.AddProperty(Property)

        # Set the parent classes
        for ParentClassName in GetClassParentNames(Class):
            ClassInstance.AddParent(ParentClassName)

        return ClassInstance

    def _GenerateFunctionInstances(self, Function) -> List[StubFunction]:
        """ 
        Generate StubFunction instances from a function reference.

        Args:
            - Function {function}: reference to the function

        Returns: A list of function instances, can be multiple if it has overload versions
        """
        FunctionName = GetObjectName(Function)

        StubFunctions = []

        # Get param & returntype info from the docstring
        FunctionInfo = GetFunctionInfoFromDocString(Function)
        for Parameters, ReturnType in FunctionInfo:
            StubFunctionInstance = StubFunction(FunctionName, Parameters, ReturnType)

            # If multiple versions of this function exists, set the functions to be overloads
            StubFunctionInstance.bIsOverload = len(FunctionInfo) > 1

            StubFunctions.append(StubFunctionInstance)

        return StubFunctions

    # ---------------------------------------------------
    #           Online Documentation Functions
    # --------------------------------------------------

    def _PatchPropertyType(self, PropertyType: str):
        """ 
        Patch a class property type, e.g. turning 'FBPropertyCamera' -> 'FBCamera'
        """
        # Default property types to always accept as valid
        if PropertyType in ["str", "float", "bool", "int"]:
            return PropertyType
        
        # Check if PropertyType exists as a known type to be translated into something else
        if PropertyType in PropertyTypeTranslation:
            return PropertyTypeTranslation[PropertyType]

        # Remove FBProperty / FBPropertyAnimatable
        if PropertyType.startswith("FBProperty") and not PropertyType.startswith("FBPropertyList"):
            StrPartToRemove = "PropertyAnimatable" if PropertyType.startswith("FBPropertyAnimatable") else "Property"
            NewPropertyType = PropertyType.replace(StrPartToRemove, "", 1)
            if NewPropertyType in self.GetAllClassNames():
                return NewPropertyType

        if PropertyType in self.GetAllClassNames():
            return PropertyType

        self._DebugPropertiesConvertedToDefault.append(PropertyType)
        return "property"
    
    def _PatchParameter(self, StubParameterInstance: StubParameter):
        if StubParameterInstance.DefaultValue:
            if StubParameterInstance.DefaultValue.startswith("k"):
                StubParameterInstance.DefaultValue = "%s.%s" % (StubParameterInstance.Type, StubParameterInstance.DefaultValue)

    def _PatchFunctionsFromDocumentation(self, Functions: List[StubFunction], DocumentationMembers = None):
        UsedDocumentations = []
        for StubFunctionInstance in Functions:
            Documentations = []
            if DocumentationMembers:
                Documentations = DocumentationMembers
            else:
                Documentations = self.DocumentationParser.GetSDKFunctionByName(StubFunctionInstance.Name)
                if not Documentations:
                    # Try adding FB
                    Documentations = self.DocumentationParser.GetSDKFunctionByName("FB%s" % StubFunctionInstance.Name)
                    if not Documentations:
                        continue

            # If it's a method
            StubParameterInstances = StubFunctionInstance.GetParameters()[1:] if StubFunctionInstance.bIsMethod else StubFunctionInstance.GetParameters()

            Documentation = None
            if StubFunctionInstance.bIsOverload:
                HighestScore = -1
                BestMatch = None
                for Doc in Documentations:
                    if Doc in UsedDocumentations:
                        continue

                    # Check if number of parameters match
                    if len(Doc.Params) != len(StubParameterInstances):
                        continue

                    # Find the one with highest matching parameter score
                    Score = 0
                    for Parameter, DocumentationParam in zip(StubParameterInstances, Doc.Params):
                        ParamType = DocumentationParam.GetType(bConvertToPython = True)
                        if Parameter.Type == ParamType:
                            Score += 1

                    if Score > HighestScore:
                        BestMatch = Doc

                if BestMatch:
                    Documentation = BestMatch
                    UsedDocumentations.append(Documentation)

            else:
                Documentation = Documentations[0]

            if not Documentation:
                continue

            # Patch the return type
            if StubFunctionInstance.ReturnType is None or StubFunctionInstance.ReturnType in ["object", "tuple"]:
                NewReturnType = Documentation.GetType(bConvertToPython = True)
                if NewReturnType and NewReturnType != "None":
                    StubFunctionInstance.ReturnType = NewReturnType

            # Patch the parameters
            DocumentationParam: docParser.DocMemberParameter
            for Parameter, DocumentationParam in zip(StubParameterInstances, Documentation.Params):
                Parameter.Name = DocumentationParam.Name
                if Parameter.DefaultValue is not None:
                    NewDefaultValue = DocumentationParam.GetDefaultValue(bConvertToPython = True)
                    if NewDefaultValue:
                        Parameter.DefaultValue = NewDefaultValue
                if Parameter.Type == "object":
                    Parameter.Type = DocumentationParam.GetType(bConvertToPython = True)
                self._PatchParameter(Parameter)
                
            # TODO: Patch docstring
            Documentation.DocString

    def _PatchClassFromDocumentation(self, Classes: List[StubClass]):
        for StubClassInstance in Classes:
            DocumentationClassName = TranslationDocumentationClassNames.get(StubClassInstance.Name, StubClassInstance.Name)
            Documentation = self.DocumentationParser.GetSDKClassPagesByName(DocumentationClassName)
            if not Documentation:
                continue

            # Patch functions
            # First collect all functions with the same name, so we itterate over them at the same time
            StubFunctionsInstancesDict = {}
            for StubFunctionInstance in StubClassInstance.StubFunctions:
                Value = StubFunctionsInstancesDict.get(StubFunctionInstance.Name, [])
                Value.append(StubFunctionInstance)
                StubFunctionsInstancesDict[StubFunctionInstance.Name] = Value

            for StubFunctionName, StubFunctionInstances in StubFunctionsInstancesDict.items():
                DocumentationFunctionName = TranslationDocumentationMethodNames.get(StubFunctionName, StubFunctionName)
                if DocumentationFunctionName == "__init__":
                    DocumentationFunctionName = DocumentationClassName
                FunctionDocumentations = Documentation.GetMembersByName(DocumentationFunctionName)
                self._PatchFunctionsFromDocumentation(StubFunctionInstances, FunctionDocumentations)

            # Patch properties
            for StubPropertyInstance in StubClassInstance.GetStubProperties():
                DocumentationMembers = Documentation.GetMembersByName(StubPropertyInstance.Name)
                if not DocumentationMembers:
                    continue

                # Properties doesn't have overloads, so we can get the first result
                PropertyDocumentation = DocumentationMembers[0]

                if StubPropertyInstance.Type == "property":
                    NewType = PropertyDocumentation.GetType(bConvertToPython = True)
                    NewType = self._PatchPropertyType(NewType)
                    StubPropertyInstance.Type = NewType

            # TODO: Add Docstring

    def GenerateString(self, bUseOnlineDocumentation = True):
        """ 
        Returns: The stub file as a string
        """
        # Get the content
        Functions, Classes, Enums = GetPyfbsdkContent()

        # Generate the initial classes & functions
        self.Enums = [self._GenerateEnumInstance(Enum) for Enum in Enums]
        self.Classes = [self._GenerateClassInstance(Class) for Class in Classes]
        # Sort classes so that if there is if a class has a parent class, that parent comes before the child
        for Function in Functions:
            self.Functions.extend(self._GenerateFunctionInstances(Function))

        # Use the online documentation to try and create better param names, values etc.
        if bUseOnlineDocumentation:
            self._PatchFunctionsFromDocumentation(self.Functions)
            self._PatchClassFromDocumentation(self.Classes)
            # c = [x for x in self.Classes if x.Name == "FBVector3d"]
            # self._PatchClassFromDocumentation(c)

        # Sort classes after all patches are done and we know their requirements
        self.Classes = SortClasses(self.Classes)

        # Generate a string
        StubString = GetCustomAdditions()  # Read the custom additions file first
        StubString += "\n".join([x.GetAsString() for x in self.Enums])
        StubString += "\n"
        StubString += "\n".join([x.GetAsString() for x in self.Classes])
        StubString += "\n"
        StubString += "\n".join([x.GetAsString() for x in self.Functions])

        print(self._DebugPropertiesConvertedToDefault)

        return StubString


def GeneratePYFBSDKStub(Filepath):
    Generator = PyfbsdkStubGenerator()

    FileContent = Generator.GenerateString()

    with open(Filepath, "w+") as File:
        File.write(FileContent)


def main():
    StartTime = time.time()

    MotionBuilderVersion = GetMotionBuilderVersion()
    Filepath = os.path.join(DEFAULT_OUTPUT_DIR, "motionbuilder-%s" % MotionBuilderVersion, "pyfbsdk.py")
    GeneratePYFBSDKStub(Filepath)

    GenerationTime = time.time() - StartTime
    print("Generating pyfbsdk stub file took: %ss." % round(GenerationTime, 2))


main()
