from __future__ import annotations

ALWAYS_CREATE_ELLIPSIS = True
TAB_CHARACTER = "    "

def Indent(Text: str):
    return TAB_CHARACTER + f"\n{TAB_CHARACTER}".join(Text.split("\n"))


class StubBase():
    def __init__(self, Ref, Name = "") -> None:
        self.Ref = Ref
        self.Name: str = Name
        self.DocString = ""

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.Name}>"

    def GetAsString(self) -> str:
        """
        Get instance as python code (in string format)
        """
        raise NotImplementedError("GetAsString() has not yet been implemented")

    def GetDocString(self):
        if self.DocString:
            return f'""\"{self.DocString.strip()}"""'
        return ""

    def GetRequirements(self) -> list:
        """
        Get a list of variable/class names that needs to be declared before the current object
        """
        raise NotImplementedError("GetRequirements() has not yet been implemented")


class StubFunction(StubBase):
    def __init__(self, Ref, Name = "", Parameters = None, ReturnType = None):
        super().__init__(Ref, Name = Name)
        self._Params: list[StubParameter] = Parameters if Parameters else []
        self.ReturnType = ReturnType
        self.bIsMethod = False
        self.bIsStatic = False
        self.bIsOverload = False

    def AddParameter(self, Parameter):
        self._Params.append(Parameter)

    def GetParameters(self) -> list[StubParameter]:
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

        FunctionAsString += f'def {self.Name}({self.GetParamsAsString()})'

        if self.ReturnType and self.ReturnType != "None":
            FunctionAsString += f'->{self.ReturnType}'

        FunctionAsString += ":"

        DocString = self.GetDocString()
        if DocString:
            FunctionAsString += f"\n{Indent(DocString)}"
            if ALWAYS_CREATE_ELLIPSIS:
                FunctionAsString += f"\n{Indent('...')}"
        else:
            FunctionAsString += "..."

        return FunctionAsString


class StubClass(StubBase):
    def __init__(self, Ref, Name = ""):
        super().__init__(Ref, Name = Name)
        self.Parents = []
        self.StubProperties: list[StubProperty] = []
        self.StubEnums: list[StubClass] = []
        self.StubFunctions: list[list[StubFunction]] = []

    def GetFunctionsByName(self, Name: str):
        return [x for x in self.StubFunctions if x.Name == Name]

    def GetPropertyByName(self, Name: str):
        for x in self.StubProperties:
            if x.Name == Name:
                return x

    def AddEnum(self, Enum: StubClass):
        self.StubEnums.append(Enum)

    def AddFunctions(self, Functions: list[StubFunction]):
        for Function in Functions:
            Function.bIsMethod = True  # Make function a method
        self.StubFunctions.append(Functions)
        
    def GetFunctionsFlat(self) -> list[StubFunction]:
        """ Get a flat list of functions """
        return [x for FunctionGroup in self.StubFunctions for x in FunctionGroup]

    def AddProperty(self, Property: StubProperty):
        self.StubProperties.append(Property)

    def AddParent(self, Parent: str):
        self.Parents.append(Parent)

    def GetStubProperties(self) -> list[StubProperty]:
        return self.StubProperties

    def GetRequirements(self) -> list:
        # The class parent's needs to be declared before the class
        FunctionRequirements = []
        for Function in self.GetFunctionsFlat():
            FunctionRequirements += Function.GetRequirements()
        return self.Parents + FunctionRequirements

    def GetAsString(self):
        ParentClassesAsString = ','.join(self.Parents)

        ClassAsString = f"class {self.Name}({ParentClassesAsString}):\n"

        if self.GetDocString():
            ClassAsString += f"{Indent(self.GetDocString())}\n"

        ClassMembers = self.StubEnums + self.StubProperties + self.GetFunctionsFlat()
        for StubObject in ClassMembers:
            ClassAsString += f"{Indent(StubObject.GetAsString())}\n"

        # If class doesn't have any members, add a '...'

        if not ClassMembers:
            ClassAsString += Indent("...")

        return ClassAsString.strip()


class StubProperty(StubBase):
    def __init__(self, Ref, Name = ""):
        super().__init__(Ref, Name = Name)
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
        PropertyAsString = f"{self.Name}:{self.Type}"

        # Add docstring
        if self.GetDocString():
            PropertyAsString += "\n"
            PropertyAsString += self.GetDocString()

        return PropertyAsString


class StubParameter(StubBase):
    def __init__(self, Ref, Name = "", Type = "", DefaultValue = None):
        super().__init__(Ref, Name = Name)
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
        if ReturnValue.startswith("p") and not ReturnValue[1].isnumeric():
            ReturnValue = ReturnValue.lstrip("p")
        if self.Type == "bool" and not ReturnValue.startswith("b"):
            ReturnValue = f"b{ReturnValue}"
        return ReturnValue

    def GetAsString(self):
        ParamString = self.GetNiceName()  # PatchParameterName(self.Name)
        # Some parameters have a 0 instead of 'None'
        if self.DefaultValue == "0" and self.Type not in (None, "float", "int"):
            self.DefaultValue = "None"

        if self.Type and self.Type != "object":
            TypeStr = self.Type
            if self.DefaultValue == "None":
                TypeStr = f"Optional[{TypeStr}]"
            ParamString += f":{TypeStr}"

        if self.DefaultValue is not None:
            ParamString += f"={self.DefaultValue}"

        return ParamString