import Foundation

public struct WorkerRequest: Codable, Sendable, Equatable {
    public let jobID: String
    public let modelPath: String
    public let imagePath: String
    public let maskPath: String
    public let outputPath: String
    public let width: Int
    public let height: Int

    public init(jobID: String, modelPath: String, imagePath: String, maskPath: String, outputPath: String, width: Int = 512, height: Int = 512) {
        self.jobID = jobID
        self.modelPath = modelPath
        self.imagePath = imagePath
        self.maskPath = maskPath
        self.outputPath = outputPath
        self.width = width
        self.height = height
    }
}

public struct WorkerResponse: Codable, Sendable, Equatable {
    public let jobID: String
    public let status: String
    public let error: String?
    public let outputPath: String?
    public let loadSeconds: Double?
    public let predictSeconds: Double?

    public init(jobID: String, status: String, error: String? = nil, outputPath: String? = nil, loadSeconds: Double? = nil, predictSeconds: Double? = nil) {
        self.jobID = jobID
        self.status = status
        self.error = error
        self.outputPath = outputPath
        self.loadSeconds = loadSeconds
        self.predictSeconds = predictSeconds
    }
}
